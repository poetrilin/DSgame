import json
import re
import os
import pickle as pkl
from collections import Counter

from config import *  # const & paras
from utils import count_num_files


def bulid_vocab_counter(data_dir):
    '''
    统计所有词汇，建立词频表
    '''
    split_dir = os.path.join(data_dir, "train")
    n_data = count_num_files(split_dir)
    vocab_counter = Counter()
    for i in range(n_data):
        js = json.load(
            open(os.path.join(split_dir, '{}.json'.format(i)), encoding='utf-8'))

        summary = js['summary']
        summary_text = ' '.join(summary).strip()
        summary_word_list = summary_text.strip().split(' ')

        review = js['source']
        review_text = ' '.join(review).strip()
        review_word_list = review_text.strip().split(' ')

        all_tokens = summary_word_list + review_word_list
        vocab_counter.update([t for t in all_tokens if t != ""])

    with open(os.path.join(data_dir, VOCAB_FREQ_PATH),
              'wb') as vocab_file:
        pkl.dump(vocab_counter, vocab_file)


def MakeVocab(vocab_size=VOCAB_SIZE):
    '''
    建立词典,通过vocab_size设置字典大小,将常用词设置到字典即可,其他生僻词汇用'<unk>'表示
    '''
    with open(VOCAB_FREQ_PATH, "rb") as f:
        if f is None:
            raise Exception("No vocab freq file found")
        wc = pkl.load(f)
    word2idx, idx2word = {}, {}
    word2idx[PAD_WORD] = 0
    word2idx[UNK_WORD] = 1
    word2idx[BOS_WORD] = 2
    word2idx[EOS_WORD] = 3
    for i, (w, _) in enumerate(wc.most_common(vocab_size), 4):
        word2idx[w] = i
    for w, i in word2idx.items():
        idx2word[i] = w

    with open(WORD_IDX_PATH, "wb") as f:
        pkl.dump(word2idx, f)
    with open(IDX_WORD_PATH, "wb") as f:
        pkl.dump(idx2word, f)


bulid_vocab_counter()
# MakeVocab()
