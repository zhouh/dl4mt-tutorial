#!/usr/bin/env python
# coding=utf-8

import sys

f = open(sys.argv[1])

for line in f:
    if line.startswith('BLEU'):
        tokens = line.split(',')
        print tokens[0].split('=')[1]
    else:
        tokens = line.split('trans')[1]
        print tokens.split('.')[0], '\t',
