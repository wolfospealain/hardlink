#!/usr/bin/python3

"""
Change to using tempfile.TemporaryDirectory().
Changed generation of test data.
Added skip()
"""

import os
import sys
import tempfile
import time
import unittest
import hardlink


class OriginalTests(unittest.TestCase):

    def setUp(self):
        pass

    def create_temporary_files(self, root):
        os.chdir(root)
        for directory in ("dir1", "dir2", "dir3", "dir4", "dir5"):
            os.mkdir(directory)
        test_data1 = "abcdefghijklmnopqrstuvwxyz" * 1024
        test_data2 = test_data1[:-1] + "2"
        self.files = {"dir1/name1.ext": test_data1, "dir1/name2.ext": test_data1, "dir1/name3.ext": test_data2,
                       "dir2/name1.ext": test_data1, "dir3/name1.ext": test_data2, "dir3/name1.noext": test_data1,
                       "dir4/name1.ext": test_data1}
        now = time.time()
        for filename, contents in self.files.items():
            with open(filename, "w") as f:
                f.write(contents)
                os.utime(filename, (now, now))
        os.utime("dir4/name1.ext", (now-2, now-2))
        os.link("dir1/name1.ext", "dir1/link")
        self.verify_file_contents()

    def verify_file_contents(self):
        for filename, contents in self.files.items():
            with open(filename, "r") as f:
                actual = f.read()
                self.assertEqual(actual, contents)

    #@unittest.skip("")
    def test_hardlink_tree_dryrun(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_temporary_files(root)
            sys.argv = ["hardlink.py", "-v", "0", "-q", "--dry-run", root]
            hardlink.main()
            self.verify_file_contents()
            self.assertEqual(os.lstat("dir1/name1.ext").st_nlink, 2)  # Existing link
            self.assertEqual(os.lstat("dir1/name2.ext").st_nlink, 1)
            self.assertEqual(os.lstat("dir1/name3.ext").st_nlink, 1)
            self.assertEqual(os.lstat("dir2/name1.ext").st_nlink, 1)
            self.assertEqual(os.lstat("dir3/name1.ext").st_nlink, 1)
            self.assertEqual(os.lstat("dir3/name1.noext").st_nlink, 1)
            self.assertEqual(os.lstat("dir4/name1.ext").st_nlink, 1)

    #@unittest.skip("")
    def test_hardlink_tree(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_temporary_files(root)
            sys.argv = ["hardlink.py", "-v", "0", "-q", root]
            hardlink.main()
            self.verify_file_contents()
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir1/name2.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir2/name1.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir3/name1.noext").st_ino)
            self.assertEqual(os.lstat("dir1/name3.ext").st_ino, os.lstat("dir3/name1.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir4/name1.ext").st_ino)

    #@unittest.skip("")
    def test_hardlink_tree_filenames_equal(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_temporary_files(root)
            sys.argv = ["hardlink.py", "-v", "0", "-q", "--filenames-equal", root]
            hardlink.main()
            self.verify_file_contents()
            self.assertNotEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir1/name2.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir2/name1.ext").st_ino)
            self.assertNotEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir3/name1.noext").st_ino)
            self.assertNotEqual(os.lstat("dir1/name3.ext").st_ino, os.lstat("dir3/name1.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir4/name1.ext").st_ino)

    #@unittest.skip("")
    def test_hardlink_tree_exclude(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_temporary_files(root)
            sys.argv = ["hardlink.py", "-v", "0", "-q", "--exclude", ".*noext$", root]
            hardlink.main()
            self.verify_file_contents()
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir1/name2.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir2/name1.ext").st_ino)
            self.assertNotEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir3/name1.noext").st_ino)
            self.assertEqual(os.lstat("dir1/name3.ext").st_ino, os.lstat("dir3/name1.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir4/name1.ext").st_ino)

    #@unittest.skip("")
    def test_hardlink_tree_timestamp(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_temporary_files(root)
            sys.argv = ["hardlink.py", "-v", "0", "-q", "-T", root]
            hardlink.main()
            self.verify_file_contents()
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir1/name2.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir2/name1.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir3/name1.noext").st_ino)
            self.assertEqual(os.lstat("dir1/name3.ext").st_ino, os.lstat("dir3/name1.ext").st_ino)
            self.assertNotEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir4/name1.ext").st_ino)

    #@unittest.skip("")
    def test_hardlink_tree_match(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_temporary_files(root)
            sys.argv = ["hardlink.py", "-v", "0", "-q", "--match", "*.ext", root]
            hardlink.main()
            self.verify_file_contents()
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir1/name2.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir2/name1.ext").st_ino)
            self.assertNotEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir3/name1.noext").st_ino)
            self.assertEqual(os.lstat("dir1/name3.ext").st_ino, os.lstat("dir3/name1.ext").st_ino)
            self.assertEqual(os.lstat("dir1/name1.ext").st_ino, os.lstat("dir4/name1.ext").st_ino)

    def tearDown(self):
        pass


class ClusterTests(unittest.TestCase):

    def setUp(self):
        pass

    def create_files(self, root):
        os.chdir(root)
        test_data1 = "abcdefghijklmnopqrstuvwxyz" * 1024
        self.files = {"1a": test_data1, "2a": test_data1}
        now = time.time()
        for filename, contents in self.files.items():
            with open(filename, "w") as f:
                f.write(contents)
                os.utime(filename, (now, now))
        os.link("1a", "1b")
        os.link("2a", "2b")
        os.link("2a", "2c")
        os.link("2a", "2d")
        os.link("2a", "2e")
        self.verify_file_contents()

    def verify_file_contents(self):
        for filename, contents in self.files.items():
            with open(filename, "r") as f:
                actual = f.read()
                self.assertEqual(actual, contents)

    #@unittest.skip("")
    def test_hardlink_cluster(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_files(root)
            sys.argv = ["hardlink.py", "-v", "0", "-q", root]
            hardlink.main()
            self.verify_file_contents()
            self.assertEqual(os.lstat("1a").st_ino, os.lstat("1b").st_ino)
            self.assertEqual(os.lstat("1a").st_ino, os.lstat("2a").st_ino)
            self.assertEqual(os.lstat("1a").st_ino, os.lstat("2b").st_ino)
            self.assertEqual(os.lstat("1a").st_ino, os.lstat("2c").st_ino)
            self.assertEqual(os.lstat("1a").st_ino, os.lstat("2d").st_ino)
            self.assertEqual(os.lstat("1a").st_ino, os.lstat("2e").st_ino)

    def tearDown(self):
        pass


class BasicTests(unittest.TestCase):

    def setUp(self):
        pass

    def create_files(self, root):
        os.chdir(root)
        test_data1 = "abcdefghijklmnopqrstuvwxyz" * 1024
        test_data2 = test_data1+ "0"
        test_data3 = test_data1[:-1] + "0"
        for directory in ("a", "b"):
            os.mkdir(directory)
        self.files = {"a/A1": test_data1, "a/B1": test_data1, "a/C2": test_data2, "b/D1": test_data1, "b/E2": test_data2, "b/F3": test_data3, "b/G3": test_data3}
        self.now = time.time()-10
        for filename, contents in self.files.items():
            with open(filename, "w") as f:
                f.write(contents)
                os.utime(filename, (self.now, self.now))
        os.link("b/F3", "b/h3")
        os.utime("a/A1", (self.now, self.now))
        os.utime("b/E2", (self.now, self.now))
        self.verify_file_contents()

    def verify_file_contents(self):
        for filename, contents in self.files.items():
            with open(filename, "r") as f:
                actual = f.read()
                self.assertEqual(actual, contents)

    #@unittest.skip("")
    def test_basic_test(self):
        with tempfile.TemporaryDirectory() as root:
            self.create_files(root)
            sys.argv = ["hardlink.py", "-v", "0", "-q", root]
            hardlink.main()
            self.verify_file_contents()
            self.assertEqual(os.lstat("a/A1").st_ino, os.lstat("a/B1").st_ino)
            self.assertEqual(os.lstat("a/C2").st_ino, os.lstat("b/E2").st_ino)
            self.assertNotEqual(os.lstat("a/A1").st_ino, os.lstat("a/C2").st_ino)
            self.assertEqual(os.lstat("a/A1").st_mtime, self.now) # latest attributes
            self.assertEqual(os.lstat("b/E2").st_mtime, self.now) # latest attributes

    def tearDown(self):
        pass


if __name__ == '__main__':
    unittest.main()
