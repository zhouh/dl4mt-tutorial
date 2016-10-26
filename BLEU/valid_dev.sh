#!/bin/bash
#PBS -l nodes=1:ppn=24
#PBS -l walltime=24:00:00
#PBS -N session2_default
#PBS -A course
#PBS -q ShortQ

#export THEANO_FLAGS=device=cpu,floatX=float32

#cd $PBS_O_WORKDIR

for((i=500000;i<504000;i=i+1000));
do ./multi-bleu.perl ../data/zh2en/devntest/MT02/reference < ../session2/output/MT02.trans${i}.en>>output.log;
done

