#!/usr/bin/python3

"""
Scan for and hardlink identical files.
https://github.com/wolfospealain/hardlinkpy
Wolf Ó Spealáin, July 2018
Licenced under the GNU General Public License v3.0. https://www.gnu.org/licenses/gpl.html
Forked from hardlink.py https://github.com/akaihola/hardlinkpy,
from the original Python code by John L. Villalovos https://code.google.com/archive/p/hardlinkpy/,
from the original hardlink.c code by Jakub Jelinek;
restructured and refactored as Python 3 object-oriented code:
new database structure and algorithm development for complete single-pass hardlinking,
option to skip re-comparing known inodes this runtime,
persistent database file option for efficient data collection on dry-run passes and for incremental scans,
with correct statistics for dry-run scans.
"""

import subprocess, sys, os, re, time, fnmatch, filecmp, argparse, logging, pickle


class File:
    """Defines an file inode object based on os.scandir() DirEntry"""

    def __init__(self, directory_entry):
        self.inodes = [directory_entry.stat().st_ino]
        self.device = directory_entry.stat().st_dev
        self.size = directory_entry.stat().st_size
        self.time = directory_entry.stat().st_mtime
        self.access_time = directory_entry.stat().st_atime
        self.mode = directory_entry.stat().st_mode
        self.uid = directory_entry.stat().st_uid
        self.gid = directory_entry.stat().st_gid
        self.path = directory_entry.path
        self.name = directory_entry.name
        self.links = directory_entry.stat().st_nlink
        # record of original filenames, inode, links, current links and new links
        self.files = {self.path: (directory_entry.stat().st_ino, self.links, 0)}

    def hardlink(self, other, dry_run=False, verbose=0):
        """Hardlink two inodes together, keeping latest attributes. Backtrack through any unlinked files. Returns updated source file object and any cleared file object."""
        # use the file with most hardlinks as source
        linked_inodes = []
        if other.links > self.links:
            logging.debug("BACKTRACKING")
            source = other
            destination = self
            redundant = self
        else:
            source = self
            destination = other
            redundant = False
        for filename in destination.files:
            # attempt file rename
            temporary_name = filename + ".$$$___cleanit___$$$"
            try:
                if not dry_run:
                    os.rename(filename, temporary_name)
            except OSError as error:
                print("\nERROR: Failed to rename: %s to %s: %s" % (filename, temporary_name, error))
                continue
            else:
                # attempt hardlink
                try:
                    if not dry_run:
                        logging.debug("HARDLINKING " + strip_invalid_characters(source.path) + " " + strip_invalid_characters(filename))
                        os.link(source.path, filename)
                except Exception as error:
                    print("\nERROR: Failed to hardlink: %s to %s: %s" % (strip_invalid_characters(source.path), strip_invalid_characters(filename), error))
                    # attempt recovery
                    try:
                        os.rename(temporary_name, filename)
                    except Exception as error:
                        print("\nALERT: Failed to rename back %s to %s: %s" % (temporary_name, filename, error))
                    return False, False
                else:
                    # hardlink succeeded
                    logging.debug("SOURCE " + strip_invalid_characters(source.path) + " " + str(source.links))
                    logging.debug("DESTINATION " + strip_invalid_characters(filename) + " " + str(destination.original_links(filename)))
                    # adjust link counts for repeated inodes
                    inode = destination.original_inode(filename)
                    if inode in linked_inodes:
                        destination.decrement_links(filename, linked_inodes.count(inode))
                    linked_inodes.append(inode)
                    # update file links
                    source.new_filename(filename, destination.original_inode(filename), destination.original_links(filename),
                                        source.links - destination.total_links(filename) + 1)
                    source.increment_links(source.path)
                    # update to latest attributes
                    if destination.time > source.time:
                        try:
                            if not dry_run:
                                os.chown(filename, destination.uid, destination.gid)
                                os.utime(filename, (destination.access_time, destination.time))
                                source.access_time = destination.access_time
                        except Exception as error:
                            print("\nERROR: Failed to update file attributes: %s" % error)
                        else:
                            source.time = destination.time
                            source.uid = destination.uid
                            source.gid = destination.gid
                    # delete temporary file
                    if not dry_run:
                        os.unlink(temporary_name)
                    if verbose >= 1:
                        if dry_run:
                            print("\nDry Run: ", end="")
                        else:
                            print("\n Linked: ", end="")
                        print("%s (%i links)" % (source.path, source.links - 1))
                        print("     to: %s (%i links)" % (filename, destination.total_links(filename)))
                        print("         %s saved" % human(
                            destination.size if destination.total_links(filename) == 1 else 0))
        return source, redundant

    def new_filename(self, filename, inode, links, new):
        if new:
            self.links += 1
        self.files.update({filename: (inode, links, new)})
        if inode not in self.inodes:
            self.inodes.append(inode)

    def increment_links(self, filename):
        self.files[filename] = (
            self.original_inode(filename), self.original_links(filename), self.new_links(filename) + 1)

    def decrement_links(self, filename, links):
        self.files[filename] = (
            self.original_inode(filename), self.original_links(filename) - links, self.new_links(filename))

    def inode(self):
        return self.inodes[0]
    
    def original_inode(self, filename):
        return self.files[filename][0]

    def original_links(self, filename):
        return self.files[filename][1]

    def new_links(self, filename):
        return self.files[filename][2]

    def total_links(self, filename):
        return self.new_links(filename) + self.original_links(filename)

    def __eq__(self, other):
        return self.inode() == other.inode()

    def __mul__(self, other):
        return self.hardlink(other)


class Database:
    """Defines the file database: fingerprints, inodes, and filenames and link counts."""

    def __init__(self):
        self.start_time = time.time()
        self.skipped = 0
        self.fingerprints = {}

    def text_dump(self):
        """Text dump from database. For debugging, development and testing."""
        text= "\n"
        for fingerprint in self.fingerprints:
            text += "\n +-" + str(fingerprint)
            for inode in self.fingerprints[fingerprint]:
                file = self.fingerprints[fingerprint][inode]
                text += "\n\n    " + str(inode) + " " + time.ctime(file.time) + " - " + str(file.links)
                for filename in file.files:
                    text += "\n       " + str(file.original_inode(filename)) + " " + strip_invalid_characters(filename) + " " + str(file.original_links(filename)) + ", " + str(file.new_links(filename)) + "\n"
        return text + "\n"

    def load(self, filename):
        if os.path.isfile(filename):
            self.fingerprints = pickle.load(open(filename, "rb"))

    def save(self, filename):
        # clear list of known compared inodes this run
        for fingerprint in self.fingerprints:
            for inode in self.fingerprints[fingerprint]:
                self.fingerprints[fingerprint][inode].inodes = self.fingerprints[fingerprint][inode].inode()
        pickle.dump(self.fingerprints, open(filename, "wb"))

    def new_fingerprint(self, file, fingerprint):
        logging.debug("NEW FINGERPRINT " + str(fingerprint))
        self.fingerprints[fingerprint] = {}
        self.new_file(file, fingerprint)

    def new_file(self, file, fingerprint):
        logging.debug("NEW FILE " + str(fingerprint) + " " + str(file.inode()))
        self.fingerprints[fingerprint].update({(file.device, file.inode()): file})
        if logging.getLogger().level == logging.DEBUG:
            logging.debug(self.text_dump())

    def update(self, file, fingerprint):
        logging.debug("UPDATE INODE " + str(file.inode()))
        self.fingerprints[fingerprint][(file.device, file.inode())] = file
        if logging.getLogger().level == logging.DEBUG:
            logging.debug(self.text_dump())

    def delete(self, file, fingerprint):
        logging.debug("DELETE INODE " + str(file.inode))
        del self.fingerprints[fingerprint][(file.device, file.inode())]
        if logging.getLogger().level == logging.DEBUG:
            logging.debug(self.text_dump())

    def lookup(self, fingerprint, inode):
        return self.fingerprints[fingerprint][inode]

    def report_linked(self):
        inodes = {}
        for fingerprint in self.fingerprints:
            for inode in self.fingerprints[fingerprint]:
                file = self.fingerprints[fingerprint][inode]
                for filename in file.files:
                    if file.original_links(filename) > 1:
                        if file.original_inode(filename) in inodes.keys():
                            inodes[file.original_inode(filename)][1].append(filename)
                        else:
                            inodes.update({file.original_inode(filename): (file.size, [filename])})
        text = ""
        for inode in sorted(inodes.keys()):
            text += "\n\nInode " + str(inode) + " (" + human(inodes[inode][0]) + ") Linked:"
            for filename in sorted(inodes[inode][1]):
                text += "\n  " + str(filename)
        if text != "":
            text = "\nALREADY HARDLINKED" + text
        else:
            text = "\nNO FILES ALREADY HARDLINKED"
        return text

    def report_links(self):
        text = ""
        for fingerprint in sorted(self.fingerprints.keys()):
            for inode in sorted(self.fingerprints[fingerprint].keys()):
                file = self.fingerprints[fingerprint][inode]
                if file.new_links(file.path) > 0:
                    text += "\n\nInode " + str(file.inode()) + " (" + human(
                        file.size) + ") Linked:\n"
                    text += "  " + file.path
                    for link in sorted(file.files.keys()):
                        if file.new_links(link) > 0 and link != \
                                file.path:
                            text += "\n "
                            if file.original_links(link) == 1:
                                text += "+"
                            else:
                                text += " "
                            text += link
                    break
        if text != "":
            text = "\nHARDLINKED" + text
        else:
            text = "\nNO FILES HARDLINKED"
        return text

    def statistics(self, dry_run=False):
        fingerprint_count = len(self.fingerprints)
        inode_count = 0
        file_count = 0
        already_links = 0
        added_links = 0
        updated_links = 0
        total_saved_bytes = 0
        total_saved_already = 0
        for fingerprint in self.fingerprints:
            inode_count += len(self.fingerprints[fingerprint])
            for inode in self.fingerprints[fingerprint]:
                file = self.fingerprints[fingerprint][inode]
                links_tally = {}
                saved_already = 0
                saved_bytes = 0
                size = file.size
                for filename in file.files:
                    original_inode = file.original_inode(filename)
                    original_links = file.original_links(filename)
                    new_links = file.new_links(filename)
                    file_count += 1
                    if new_links > 0:
                        if original_links > 1:
                            updated_links += 1
                        elif original_inode != \
                                file.inode():
                            saved_bytes += size
                            added_links += 1
                    if original_links > 1:
                        saved_already += size
                        already_links += 1
                    # adjust statistics for dry run - as link counts don't actually get updated on the device
                    if dry_run and original_inode != file.inode():
                        if original_inode not in links_tally:
                            links_tally.update({original_inode:(1, original_links, original_links)})
                        else:
                            links_tally.update({original_inode: (links_tally[original_inode][0]+1, min(original_links, links_tally[original_inode][1]), max(original_links, links_tally[original_inode][2]))})
                if dry_run:
                    for inode in links_tally:
                        if links_tally[inode][0] == links_tally[inode][2] and links_tally[inode][0] > 1:
                            updated_links -= 1
                            already_links -= 1
                            added_links += 1
                            saved_bytes += size
                            saved_already -= size
                if saved_already:
                    total_saved_already += saved_already - size
                if already_links:
                    already_links -= 1
                total_saved_bytes += saved_bytes
        run_time = round((time.time() - self.start_time), 3)
        return "\nSTATISTICS\n\nInodes:\t\t" + str(inode_count) + "\nFiles:\t\t" + str(
            file_count) + "\nFingerprints:\t" + str(fingerprint_count) + "\nAlready Linked:\t" + str(
            already_links) + "\nSaved Already:\t" + str(
            human(total_saved_already) + "\nSkipped:\t" + str(self.skipped) + "\nUpdated Links:\t" + str(
                updated_links) + "\nAdded Links:\t" + str(added_links) + "\nSaved Bytes:\t" + str(
                human(total_saved_bytes)) + "\nRun Time:\t" + str(run_time) + "s\n")


class SearchSpace:
    """Defines the hardlink search-space."""

    def __init__(self, directories, matching, excluding, minimum_size, maximum_size, check_name, check_timestamp,
                 check_properties):
        self.maximum_links = os.pathconf(directories[0], "PC_LINK_MAX")
        self.directories = directories
        self.matching = matching
        self.excluding = excluding
        self.minimum_size = minimum_size
        self.maximum_size = maximum_size
        self.check_name = check_name
        self.check_timestamp = check_timestamp
        self.check_properties = check_properties
        self.database = Database()

    def scan(self, verbose=0, dry_run=False, no_confirm=False):
        """Recursively scan directories checking for hardlinkable files."""
        while self.directories:
            directory = self.directories.pop() + "/"
            assert os.path.isdir(directory)
            try:
                directory_entries = os.scandir(directory)
            except OSError as error:
                print(directory, error)
                continue
            inodes_hardlinked = []
            for directory_entry in directory_entries:
                # exclude symbolic link
                if directory_entry.is_symlink():
                    continue
                # user exclusions
                exclude = False
                for pattern in self.excluding:
                    if re.search(pattern, directory_entry.path):
                        exclude = True
                        break
                if exclude:
                    continue
                # add new directory
                if directory_entry.is_dir():
                    self.directories.append(directory_entry.path)
                else:
                    new_file = File(directory_entry)
                    logging.debug("PROCESSING " + strip_invalid_characters(new_file.path) + " " + str(new_file.inode()) + " " + str(new_file.links))
                    # is a file within size limits, no zero size, under maximum links
                    if (new_file.size >= self.minimum_size) \
                            and ((new_file.size <= self.maximum_size) or (self.maximum_size == 0)) \
                            and (new_file.links < self.maximum_links) and new_file.size > 0:
                        # matching requirements
                        if self.matching:
                            if not fnmatch.fnmatch(new_file.name, self.matching):
                                continue
                        # create file index
                        if self.check_timestamp or self.check_properties:
                            fingerprint = (new_file.size, new_file.time)
                        else:
                            fingerprint = new_file.size
                        if verbose >= 3:
                            print("File: %s" % new_file.path)
                        if fingerprint in self.database.fingerprints:
                            # check for hardlink in dictionary
                            for inode in self.database.fingerprints[fingerprint]:
                                known_file = self.database.lookup(fingerprint, inode)
                                # already hardlinked
                                if (new_file.device, new_file.inode()) == inode:
                                    known_file.new_filename(new_file.path, new_file.inode(), new_file.links, 0)
                                    if not dry_run:
                                        known_file.links = new_file.links
                                    self.database.update(known_file, fingerprint)
                                    break
                            else:
                                # check if hardlinkable: samename, maximum links, properties, owner, group, time, device
                                for inode in self.database.fingerprints[fingerprint]:
                                    known_file = self.database.lookup(fingerprint, inode)
                                    if known_file.inode() != new_file.inode() \
                                            and (new_file.name == known_file.name or not self.check_name) \
                                            and known_file.links < self.maximum_links \
                                            and (new_file.mode == known_file.mode or not self.check_properties) \
                                            and (new_file.uid == known_file.uid or not self.check_properties) \
                                            and (new_file.gid == known_file.gid or not self.check_properties) \
                                            and (new_file.time == known_file.time or not self.check_timestamp) \
                                            and (new_file.device == known_file.device):
                                        # check if equal contents
                                        if verbose > 1:
                                            print("Comparing: %s" % new_file.path)
                                            print("       to: %s" % known_file.path)
                                        # check if we need to compare files or the inodes are already seen this run
                                        if new_file.inode() in known_file.inodes and no_confirm:
                                            logging.debug("ALREADY COMPARED")
                                            compared = True
                                        else:
                                            try:
                                                compared = filecmp.cmp(new_file.path, known_file.path, shallow=False)
                                            except Exception as error:
                                                compared = False
                                                print("\nERROR: Failed to compare files: %s" % error)
                                        if compared:
                                            # hardlink files
                                            if not no_confirm:
                                                answer = input(
                                                    "\nHardlinking:\n\n    " + known_file.path + "\n to " + new_file.path + "\n\nConfirm? [yes/No/all] ").lower()
                                                if answer[0] == "y" or answer[0] == "a":
                                                    ok = True
                                                    if answer[0] == "a":
                                                        no_confirm = True
                                                else:
                                                    ok = False
                                            else:
                                                ok = True
                                            if ok:
                                                update_inode, redundant_inode = known_file.hardlink(new_file, dry_run,
                                                                                                    verbose)
                                                if update_inode:
                                                    self.database.update(update_inode, fingerprint)
                                                else:
                                                    return False
                                                if redundant_inode:
                                                    self.database.delete(redundant_inode, fingerprint)
                                                else:
                                                    # keep track of inodes hardlinked this directory
                                                    inodes_hardlinked.append(new_file.inode())
                                            else:
                                                print("Skipped.")
                                                self.database.skipped += 1
                                            break
                                else:
                                    self.database.new_file(new_file, fingerprint)
                        else:
                            self.database.new_fingerprint(new_file, fingerprint)
        return True

def strip_invalid_characters(text):
    return str(text.encode("utf-8", "ignore"))

def human(number):
    """Humanize numbers, B, KiB, MiB, Gib"""
    if number > 1024 ** 3:
        return "%.3f GiB" % (number / (1024.0 ** 3))
    if number > 1024 ** 2:
        return "%.3f MiB" % (number / (1024.0 ** 2))
    if number > 1024:
        return "%.3f KiB" % (number / 1024.0)
    return "%d B" % number


def parse_command_line(version, install_path):
    description = "%(prog)s version " + version + ". " \
                  + "Scan for and hardlink identical files. https://github.com/wolfospealain/hardlinkpy"
    parser = argparse.ArgumentParser(description=description)
    if ".py" in sys.argv[0]:
        parser.add_argument("--install", action="store_true", dest="install", default=False,
                            help="install to Linux destination path (default: " + install_path + ")")
    parser.add_argument("-d", "--database", help="use persistent database file (hardlink.db)", action="store_true", dest="persistent")
    parser.add_argument("-f", "--filenames-equal", help="filenames have to be identical", action="store_true",
                        dest="check_name", default=False)
    parser.add_argument("-l", "--log", help="debugging mode (log to hardlink.log)", action="store_true", dest="log", default=False)
    parser.add_argument("-n", "--dry-run", help="dry-run only, no changes to files", action="store_true",
                        dest="dry_run", default=False)
    parser.add_argument("-p", "--print-previous", help="output list of previously created hardlinks",
                        action="store_true", dest="previous", default=False)
    parser.add_argument("-P", "--properties", help="file properties have to match", action="store_true",
                        dest="check_properties", default=False)
    parser.add_argument("-q", "--no-stats", help="skip printing statistics", action="store_false", dest="statistics",
                        default=True)
    parser.add_argument("-o", "--output", help="output list of hardlinked files", action="store_true", dest="output",
                        default=False)
    parser.add_argument("-s", "--min-size", type=int, help="minimum file size", action="store", dest="minimum_size",
                        default=0)
    parser.add_argument("-S", "--max-size", type=int, help="maximum file size", action="store", dest="maximum_size",
                        default=0)
    parser.add_argument("-T", "--timestamp", help="file modification times have to be identical", action="store_true",
                        dest="check_timestamp", default=False)
    parser.add_argument("-v", "--verbose", help="verbosity level (0, 1 default, 2, 3)", metavar="LEVEL", action="store",
                        dest="verbose", type=int, default=1)
    parser.add_argument("-x", "--exclude", metavar="REGEX",
                        help="regular expression used to exclude files/dirs (may specify multiple times)",
                        action="append", dest="excluding", default=[])
    parser.add_argument("-m", "--match", help="shell pattern used to match files", metavar="PATTERN", action="store",
                        dest="matching", default=None)
    parser.add_argument("-Y", "--no-confirm", help="hardlink without confirmation, hardlink known inodes without recomparing", action="store_true",
                        dest="no_confirm", default=False)
    parser.add_argument("directories", help="one or more search directories", nargs='*')
    args = parser.parse_args()
    if args.directories:
        directories = [os.path.abspath(os.path.expanduser(directory)) for directory in args.directories]
        for directory in directories:
            if not os.path.isdir(directory):
                parser.print_help()
                print("\nERROR: %s is NOT a directory" % directory)
                sys.exit(1)
    elif ".py" in sys.argv[0] and args.install:
        directories = [install_path]
    else:
        print("ERROR: specify one or more search directories")
        sys.exit(1)
    return args, directories


def install(target):
    """Install to target path and set executable permission."""
    if os.path.isdir(target):
        try:
            subprocess.check_output(["cp", "hardlink.py", target + "/hardlink"]).decode("utf-8")
            subprocess.check_output(["chmod", "a+x", target + "/hardlink"]).decode("utf-8")
            print("Installed to " + target + " as hardlink.")
        except:
            print("Not installed.")
            if os.getuid() != 0:
                print("Is sudo required?")
            return False
    else:
        print(target, "is not a directory.")
        return False


def main():
    version = "18.07"
    install_path = "/usr/local/bin"
    db_filename = "./hardlink.db"
    debug_filename = "./hardlink.log"
    args, directories = parse_command_line(version, install_path)
    if ".py" in sys.argv[0]:
        if args.install:
            install(directories[0])
            exit()
    if args.log:
        logging.basicConfig(filename=debug_filename, level=logging.DEBUG)
        args.excluding.append(debug_filename)
    if args.persistent:
        args.excluding.append(db_filename)
    search = SearchSpace(directories, args.matching, args.excluding, args.minimum_size, args.maximum_size,
                         args.check_name, args.check_timestamp, args.check_properties)
    if args.persistent:
        search.database.load(db_filename)
    if search.scan(args.verbose, args.dry_run, args.no_confirm):
        if args.previous:
            print(search.database.report_linked())
        if args.output:
            print(search.database.report_links())
        if args.statistics:
            print(search.database.statistics(args.dry_run))
        if args.persistent:
            search.database.save(db_filename)
    if args.dry_run:
        print("\nDRY RUN ONLY: No files were changed.\n")
    if args.log:
        logging.info(search.database.statistics(args.dry_run))

if __name__ == '__main__':
    main()
