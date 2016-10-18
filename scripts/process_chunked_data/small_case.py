#!/usr/bin/env python
# coding=utf-8

import sys

f = open(sys.argv[1])

for s in f:
    print s.strip().lower()

