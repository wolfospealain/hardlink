#!/usr/bin/python3

"""
Scan for and hardlink identical files.
https://github.com/wolfospealain/hardlink
Wolf Ó Spealáin, July 2018
Licenced under the GNU General Public License v3.0. https://www.gnu.org/licenses/gpl.html
Forked from hardlink.py https://github.com/akaihola/hardlinkpy,
from the original by John L. Villalovos https://code.google.com/archive/p/hardlinkpy/.
Restructured and refactored as Python 3 object-oriented code: new database structure and algorithm development.
"""

import subprocess, sys, os, re, time, fnmatch, filecmp, argparse, logging


class File:
    """Defines an file inode object based on os.scandir() DirEntry"""

    def __init__(self, directory_entry):
        self.inode = directory_entry.stat().st_ino
        self.device = directory_entry.stat().st_dev
        self.size = directory_entry.stat().st_size
        self.links = directory_entry.stat().st_nlink
        self.time = directory_entry.stat().st_mtime
        self.access_time = directory_entry.stat().st_atime
        self.mode = directory_entry.stat().st_mode
        self.uid = directory_entry.stat().st_uid
        self.gid = directory_entry.stat().st_gid
        self.path = directory_entry.path
        self.name = directory_entry.name
        self.files = {self.path: (self.links, 1)}  # record of inode filenames, past links and new links

    def hardlink(self, other, dry_run=False, verbose=0):
        """Hardlink two inodes together, keeping latest attributes. Backtrack through any unlinked files. Returns updated source file object and any cleared file object."""
        # use the file with most hardlinks as source
        if other.links > self.links:
            logging.debug("BACKTRACKING")
            source = other
            destination = self
            empty = self
        else:
            source = self
            destination = other
            empty = False
        for link in destination.files:
            # attempt file rename
            temporary_name = link + ".$$$___cleanit___$$$"
            try:
                if not dry_run:
                    os.rename(link, temporary_name)
            except OSError as error:
                print("ERROR: Failed to rename: %s to %s: %s" % (link, temporary_name, error))
                return False
            else:
                # attempt hardlink
                try:
                    if not dry_run:
                        logging.debug("HARDLINKING " + source.path + " " + link)
                        os.link(source.path, link)
                except Exception as error:
                    print("Failed to hardlink: %s to %s: %s" % (source.path, link, error))
                    # attempt recovery
                    try:
                        os.rename(temporary_name, link)
                    except Exception as error:
                        print("ALERT: Failed to rename back %s to %s: %s" % (temporary_name, link, error))
                    return False
                else:
                    # hardlink succeeded, update links
                    source.files.update({link: (destination.files[link][0], 1)})
                    source.files.update({source.path: (source.files[source.path][0], source.files[source.path][1] + 1)})
                    source.links += 1
                    # update to latest attributes
                    if destination.time > source.time:
                        try:
                            os.chown(link, destination.uid, destination.gid)
                            os.utime(link, (destination.access_time, destination.time))
                            source.access_time = destination.access_time
                        except Exception as error:
                            print("ERROR: Failed to update file attributes: %s" % error)
                        else:
                            source.time = destination.time
                            source.uid = destination.uid
                            source.gid = destination.gid
                    # delete temporary file
                    if not dry_run:
                        os.unlink(temporary_name)
                    if verbose >= 1:
                        if dry_run:
                            print("\nDry Run: %s" % source.path)
                        else:
                            print("\n Linked: %s" % source.path)
                        print("     to: %s" % link)
                        print("         saving %s" % human(destination.size if destination.links == 1 else 0))
            source.links += destination.links - 1
        return source, empty

    def __eq__(self, other):
        return self.inode == other.inode

    def __mul__(self, other):
        return self.hardlink(other)


class FileDatabase:
    """Defines the file database: fingerprints, inodes, and filenames and link counts."""

    def __init__(self):
        self.start_time = time.time()
        self.fingerprints = {}

    def database_dump(self):
        """Text dump from database. For debugging, development and testing."""
        print()
        for fingerprint in self.fingerprints:
            print(" +-" + str(fingerprint))
            for inode in self.fingerprints[fingerprint]:
                print("\n    " + str(inode) + " " + time.ctime(self.fingerprints[fingerprint][inode].time))
                for file in self.fingerprints[fingerprint][inode].files:
                    print("       " + file + " - " + str(
                        self.fingerprints[fingerprint][inode].files[file][0]) + ", " + str(
                        self.fingerprints[fingerprint][inode].files[file][1]))
        print()

    def fingerprint(self, file, fingerprint):
        logging.debug("NEW FINGERPRINT " + str(fingerprint))
        self.fingerprints[fingerprint] = {}
        self.new(file, fingerprint)

    def new(self, file, fingerprint):
        logging.debug("NEW INODE " + str(fingerprint) + " " + str(file.inode))
        self.fingerprints[fingerprint].update({(file.device, file.inode): file})
        if logging.getLogger().level == logging.DEBUG:
            self.database_dump()

    def update(self, file, fingerprint):
        logging.debug("UPDATE INODE " + str(file.inode))
        self.fingerprints[fingerprint][(file.device, file.inode)] = file
        if logging.getLogger().level == logging.DEBUG:
            self.database_dump()

    def archive(self, file, fingerprint):
        """To archive an inode that has no more links change the device to None."""
        logging.debug("ARCHIVE INODE " + str(file.inode))
        if (file.device, file.inode) in self.fingerprints[fingerprint]:
            self.fingerprints[fingerprint][(None, file.inode)] = self.fingerprints[fingerprint][
                (file.device, file.inode)]
            del self.fingerprints[fingerprint][(file.device, file.inode)]
        if logging.getLogger().level == logging.DEBUG:
            self.database_dump()

    def lookup(self, fingerprint, inode):
        return self.fingerprints[fingerprint][inode]

    def report_links(self, already=False):
        if already:
            index = 0
            text = "\nALREADY HARDLINKED"
        else:
            index = 1
            text = "\nHARDLINKED"
        for fingerprint in self.fingerprints:
            for inode in self.fingerprints[fingerprint]:
                if inode[0] or already:
                    for filename in self.fingerprints[fingerprint][inode].files:
                        if self.fingerprints[fingerprint][inode].files[filename][index] > 1:
                            text += "\n\nInode " + str(self.fingerprints[fingerprint][inode].inode) + " (" + human(
                                self.fingerprints[fingerprint][inode].size) + ") Linked:"
                            for link in self.fingerprints[fingerprint][inode].files:
                                if self.fingerprints[fingerprint][inode].files[link][index] > 1 or not already:
                                    text += "\n " + link
                            break
        return text

    def statistics(self):
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
                saved_already = 0
                saved_bytes = 0
                size = self.fingerprints[fingerprint][inode].size
                for file in self.fingerprints[fingerprint][inode].files:
                    if inode[0]:
                        file_count += 1
                        if self.fingerprints[fingerprint][inode].files[file][1] > 1:
                            new_links = self.fingerprints[fingerprint][inode].files[file][1] - 1
                            saved_bytes += size * new_links
                            if self.fingerprints[fingerprint][inode].files[file][0] > 1:
                                updated_links += new_links
                            else:
                                added_links += new_links
                    if self.fingerprints[fingerprint][inode].files[file][0] > 1:
                        saved_already += size
                        already_links += 1
                if saved_already:
                    total_saved_already += saved_already - size
                total_saved_bytes += saved_bytes
        run_time = round((time.time() - self.start_time), 3)
        return "\nSTATISTICS\n\nInodes:\t\t" + str(inode_count) + "\nFiles:\t\t" + str(
            file_count) + "\nFingerprints:\t" + str(fingerprint_count) + "\nAlready Linked:\t" + str(
            already_links) + "\nSaved Already:\t" + str(
            human(total_saved_already) + "\nUpdated Links:\t" + str(updated_links) + "\nAdded Links:\t" + str(added_links) + "\nSaved Bytes:\t" + str(
                human(total_saved_bytes)) + "\nRun Time:\t" + str(run_time) + "s")


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
        self.database = FileDatabase()

    def scan(self, verbose, dry_run=False):
        """Recursively scan directories checking for hardlinkable files."""
        while self.directories:
            directory = self.directories.pop() + "/"
            assert os.path.isdir(directory)
            try:
                directory_entries = os.scandir(directory)
            except OSError as error:
                print(directory, error)
                continue
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
                    logging.debug("PROCESSING " + new_file.path + " " + str(new_file.inode))
                    # is a file within size limits, under maximum links
                    if (new_file.size >= self.minimum_size) \
                            and ((new_file.size <= self.maximum_size) or (self.maximum_size == 0)) \
                            and (new_file.links < self.maximum_links):
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
                                if (new_file.device, new_file.inode) == inode:
                                    known_file.files.update({new_file.path: (known_file.links, 1)})
                                    self.database.update(known_file, fingerprint)
                                    break
                            else:
                                # check if hardlinkable: samename, maximum links, properties, owner, group, time, device
                                for inode in self.database.fingerprints[fingerprint]:
                                    known_file = self.database.lookup(fingerprint, inode)
                                    if known_file.inode != new_file.inode \
                                            and (new_file.name == known_file.name or not self.check_name) \
                                            and known_file.links < self.maximum_links \
                                            and (new_file.mode == known_file.mode or not self.check_properties) \
                                            and (new_file.uid == known_file.uid or not self.check_properties) \
                                            and (new_file.gid == known_file.gid or not self.check_properties) \
                                            and (new_file.time == known_file.time or not self.check_timestamp):
                                        # check if equal contents
                                        if verbose > 1:
                                            print("Comparing: %s" % new_file.path)
                                            print("       to: %s" % known_file.path)
                                        if filecmp.cmp(new_file.path, known_file.path, shallow=False):
                                            update_inode, clear_inode = known_file.hardlink(new_file, dry_run, verbose)
                                            self.database.update(update_inode, fingerprint)
                                            if clear_inode:
                                                self.database.archive(clear_inode, fingerprint)
                                            break
                                else:
                                    self.database.new(new_file, fingerprint)
                        else:
                            self.database.fingerprint(new_file, fingerprint)
        return True


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
                  + "Scan for and hardlink identical files. https://github.com/wolfospealain/hardlink"
    parser = argparse.ArgumentParser(description=description)
    if ".py" in sys.argv[0]:
        parser.add_argument("--install", action="store_true", dest="install", default=False,
                            help="install to Linux destination path (default: " + install_path + ")")
    parser.add_argument("-d", "--debug", help="debugging mode", action="store_true", dest="debug", default=False)
    parser.add_argument("-f", "--filenames-equal", help="filenames have to be identical", action="store_true",
                        dest="check_name", default=False)
    parser.add_argument("-n", "--dry-run", help="dry-run only, no changes to files", action="store_true",
                        dest="dry_run", default=False)
    parser.add_argument("-p", "--print-previous", help="output list of previously created hardlinks",
                        action="store_true", dest="log", default=False)
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
    args, directories = parse_command_line(version, install_path)
    if ".py" in sys.argv[0]:
        if args.install:
            install(directories[0])
            exit()
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    search = SearchSpace(directories, args.matching, args.excluding, args.minimum_size, args.maximum_size,
                         args.check_name, args.check_timestamp, args.check_properties)
    if search.scan(args.verbose, args.dry_run):
        if args.log:
            print(search.database.report_links(already=True))
        if args.output:
            print(search.database.report_links())
        if args.statistics:
            print(search.database.statistics())
    if args.dry_run:
        print("\nDRY RUN ONLY: No files were changed.")


if __name__ == '__main__':
    main()
