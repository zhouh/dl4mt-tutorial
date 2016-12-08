#!/bin/bash
#PBS -l nodes=1:ppn=24
#PBS -l walltime=24:00:00
#PBS -N session2_default
#PBS -A course
#PBS -q ShortQ


export THEANO_FLAGS=device=cpu,optimizer=None,floatX=float32,exception_verbosity=high

#cd $PBS_O_WORKDIR
python ./translate_gpu.py -n \
	./model_hal.npz  \
	./model_hal.npz.pkl  \
	../../nmtdata/small.ch.pkl \
	../../nmtdata/small.en.chunked.pkl \
	../../nmtdata/devntest/MT02/MT02.src \
	./test.result



