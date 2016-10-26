#!/bin/bash
#PBS -l nodes=1:ppn=24
#PBS -l walltime=24:00:00
#PBS -N session2_default
#PBS -A course
#PBS -q ShortQ

#export THEANO_FLAGS=device=cpu,floatX=float32

#cd $PBS_O_WORKDIR

for((i=300000;i<382000;i=i+1000));
do ./multi-bleu.perl ../data/newstest2011.fr.tok < /home/chenhd/coverage/output/newstest2011.trans${i}.fr>>enfr_cov.log;
done

