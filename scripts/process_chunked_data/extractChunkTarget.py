#!/usr/bin/env python
# coding=utf-8

import sys

f = open(sys.argv[1])

words = []
chunk_tags = []

for line in f:

    if len(line.strip()) == 0:
        for [tag, ws] in zip(chunk_tags, words):
            print '%s\t%s' %(tag, ' '.join(ws))
        print
        words = []
        chunk_tags = []
        continue

    tokens = line.strip().split()
    # word POS chunk-tag
    if len(tokens) != 3:
        print tokens
        raise Exception, 'wrong chunked words'

    word = tokens[0].lower()
    chunkTag = tokens[2]
    tag_token = chunkTag.split('-')

    if chunkTag.startswith('O'):
        words.append([word])
        chunk_tags.append('O')
    elif chunkTag.startswith('B'):
        words.append([word])
        chunk_tags.append(tag_token[1])
    elif chunkTag.startswith('I'):
        words[-1].append(word)
    else:
        raise Exception, 'wrong chunk tag'


