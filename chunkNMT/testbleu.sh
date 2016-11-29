#!/bin/bash
rm test.log
for f in ./outputs/*
do


    echo $f >> test.log
    ./BLEU/multi-bleu.perl /home/zhouh/workspace/python/nmtdata/devntest/MT02/reference < $f >> test.log


done

