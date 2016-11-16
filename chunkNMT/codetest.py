__author__ = 'zhouh'



from training_data_iterator import TrainingTextIterator


# train = TrainingTextIterator('/home/zhouh/workspace/python/nmtdata/small.ch',
#                              '/home/zhouh/workspace/python/nmtdata/small.en.chunked',
#                              '/home/zhouh/workspace/python/nmtdata/small.ch.pkl',
#                              '/home/zhouh/workspace/python/nmtdata/small.en.chunked.pkl',
#                              '/home/zhouh/workspace/python/nmtdata/small.en.chunked.chunktag.pkl',
#                               n_words_source=10000, n_words_target=10000,
#                               batch_size=32, max_chunk_len=30, max_word_len=5)

train = TrainingTextIterator('/home/zhouh/workspace/python/nmtdata/corpus.ch',
                             '/home/zhouh/workspace/python/nmtdata/corpus.en.chunked',
                             '/home/zhouh/workspace/python/nmtdata/corpus.ch.pkl',
                             '/home/zhouh/workspace/python/nmtdata/corpus.en.chunked.pkl',
                             '/home/zhouh/workspace/python/nmtdata/corpus.en.chunked.chunktag.pkl',
                              n_words_source=10000, n_words_target=10000,
                              batch_size=32, max_chunk_len=30, max_word_len=5)



n = 0
batch = 0
for i in train:
    # print batch
    batch += 1

    if batch % 1000 == 0:
        print batch
print batch

