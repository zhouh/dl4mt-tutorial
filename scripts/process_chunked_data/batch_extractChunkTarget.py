#!/usr/bin/env python
# coding=utf-8

import sys
import os


words = []
chunk_tags = []

for dir in os.listdir(sys.argv[1]):

    current_dir = sys.argv[1] + '/'+dir+'/'

    for file in os.listdir(current_dir):
        f = open(current_dir + file)
        f_handler=open(current_dir + file + '.chunked', 'w')
        sys.stdout=f_handler

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


