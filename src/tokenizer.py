import gzip
import html
import os
import numpy as np
import ftfy
import regex as re
from src.utils import get_resource_path

from functools import lru_cache
def whitespace_clean(text):
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text


@lru_cache()
def default_bpe():
    return get_resource_path("models/bpe_simple_vocab_16e6.txt.gz")


from functools import lru_cache


class SimpleTokenizer(object):
    def __init__(self, bpe_path: str = default_bpe()):
        self.byte_encoder = self.bytes_to_unicode()
        self.byte_decoder = {v: k for k, v in self.byte_encoder.items()}
        try:
            merges = gzip.open(bpe_path).read().decode("utf-8").split('\n')
        except Exception as e:
            print(f"读取词汇表失败: {e}")
            merges = []

        merges = merges[1:49152 - 256 - 2 + 1]
        merges = [tuple(merge.split()) for merge in merges]
        self.bpe_ranks = dict(zip(merges, range(len(merges))))
        self.cache = {'<|startoftext|>': '<|startoftext|>', '<|endoftext|>': '<|endoftext|>'}
        self.pat = re.compile(
            r"""<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|[\p{L}]+|[\p{N}]+|[^\s\p{L}\p{N}]+""",
            re.IGNORECASE)

        vocab = list(self.byte_encoder.values())
        vocab = vocab + [v + '</w>' for v in vocab]
        for m in merges:
            vocab.append("".join(m))
        vocab.extend(['<|startoftext|>', '<|endoftext|>'])
        self.encoder = dict(zip(vocab, range(len(vocab))))
        self.decoder = {v: k for k, v in self.encoder.items()}

    def bytes_to_unicode(self):
        bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(
            range(ord("®"), ord("ÿ") + 1))
        cs = bs[:]
        n = 0
        for b in range(256):
            if b not in bs:
                bs.append(b)
                cs.append(256 + n)
                n += 1
        cs = [chr(n) for n in cs]
        return dict(zip(bs, cs))

    def get_pairs(self, word):
        pairs = set()
        prev_char = word[0]
        for char in word[1:]:
            pairs.add((prev_char, char))
            prev_char = char
        return pairs

    def bpe(self, token):
        if token in self.cache:
            return self.cache[token]
        word = tuple(token[:-1]) + (token[-1] + '</w>',)
        pairs = self.get_pairs(word)

        if not pairs:
            return token + '</w>'

        while True:
            bigram = min(pairs, key=lambda pair: self.bpe_ranks.get(pair, float('inf')))
            if bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new_word = []
            i = 0
            while i < len(word):
                try:
                    j = word.index(first, i)
                    new_word.extend(word[i:j])
                    i = j
                except:
                    new_word.extend(word[i:])
                    break

                if word[i] == first and i < len(word) - 1 and word[i + 1] == second:
                    new_word.append(first + second)
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            word = tuple(new_word)
            if len(word) == 1:
                break
            else:
                pairs = self.get_pairs(word)
        word = ' '.join(word)
        self.cache[token] = word
        return word

    def encode(self, text):
        bpe_tokens = []
        text = whitespace_clean(ftfy.fix_text(html.unescape(text)).lower())
        for token in re.findall(self.pat, text):
            token = ''.join(self.byte_encoder[b] for b in token.encode('utf-8'))
            bpe_tokens.extend(self.encoder[bpe_token] for bpe_token in self.bpe(token).split(' '))
        return bpe_tokens


# 实例化单例
_tokenizer = SimpleTokenizer()


def tokenize(texts, context_length: int = 77):
    if isinstance(texts, str):
        texts = [texts]
    all_tokens = []
    for text in texts:
        sot_token = _tokenizer.encoder['<|startoftext|>']
        eot_token = _tokenizer.encoder['<|endoftext|>']
        # 核心修复：增加对 encode 过程中可能产生的 KeyError 的处理
        try:
            tokens = [sot_token] + _tokenizer.encode(text) + [eot_token]
        except KeyError:
            # 如果真的遇到无法解析的特殊字符，退而求其次只保留起止符
            tokens = [sot_token, eot_token]

        result = np.zeros(context_length, dtype=np.int32)
        if len(tokens) > context_length:
            tokens = tokens[:context_length]
            tokens[-1] = eot_token
        result[:len(tokens)] = tokens
        all_tokens.append(result)
    return np.array(all_tokens)