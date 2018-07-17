#!/usr/bin/python3

import cProfile, argparse, hardlink

cProfile.run('hardlink.main()', sort='cumtime')
