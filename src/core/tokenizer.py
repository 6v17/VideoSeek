import gzip
import html
from functools import lru_cache

import ftfy
import numpy as np
import regex as re

from src.utils import ensure_model_files


def whitespace_clean(text):
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@lru_cache()
def default_bpe():
    return ensure_model_files(["bpe_simple_vocab_16e6.txt.gz"])["bpe_simple_vocab_16e6.txt.gz"]


class SimpleTokenizer:
    def __init__(self, bpe_path=None):
        if bpe_path is None:
            bpe_path = default_bpe()

        self.byte_encoder = self.bytes_to_unicode()
        self.byte_decoder = {v: k for k, v in self.byte_encoder.items()}
        try:
            merges = gzip.open(bpe_path).read().decode("utf-8").split("\n")
        except Exception as exc:
            print(f"Failed to read BPE vocab: {exc}")
            merges = []

        merges = merges[1 : 49152 - 256 - 2 + 1]
        merges = [tuple(merge.split()) for merge in merges]
        self.bpe_ranks = dict(zip(merges, range(len(merges))))
        self.cache = {"<|startoftext|>": "<|startoftext|>", "<|endoftext|>": "<|endoftext|>"}
        self.pat = re.compile(
            r"""<\|startoftext\|>|<\|endoftext\|>|'s|'t|'re|'ve|'m|'ll|'d|[\p{L}]+|[\p{N}]+|[^\s\p{L}\p{N}]+""",
            re.IGNORECASE,
        )

        vocab = list(self.byte_encoder.values())
        vocab = vocab + [value + "</w>" for value in vocab]
        for merge in merges:
            vocab.append("".join(merge))
        vocab.extend(["<|startoftext|>", "<|endoftext|>"])
        self.encoder = dict(zip(vocab, range(len(vocab))))
        self.decoder = {v: k for k, v in self.encoder.items()}

    def bytes_to_unicode(self):
        # Standard CLIP byte-to-unicode table.
        bs = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
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

        word = tuple(token[:-1]) + (token[-1] + "</w>",)
        pairs = self.get_pairs(word)
        if not pairs:
            return token + "</w>"

        while True:
            bigram = min(pairs, key=lambda pair: self.bpe_ranks.get(pair, float("inf")))
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
                except ValueError:
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
            pairs = self.get_pairs(word)

        result = " ".join(word)
        self.cache[token] = result
        return result

    def encode(self, text):
        bpe_tokens = []
        text = whitespace_clean(ftfy.fix_text(html.unescape(text)).lower())
        for token in re.findall(self.pat, text):
            token = "".join(self.byte_encoder[b] for b in token.encode("utf-8"))
            bpe_tokens.extend(self.encoder[bpe_token] for bpe_token in self.bpe(token).split(" "))
        return bpe_tokens


_tokenizer = None


def get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = SimpleTokenizer()
    return _tokenizer


def tokenize(texts, context_length=77):
    tokenizer = get_tokenizer()
    if isinstance(texts, str):
        texts = [texts]

    all_tokens = []
    for text in texts:
        sot_token = tokenizer.encoder["<|startoftext|>"]
        eot_token = tokenizer.encoder["<|endoftext|>"]
        try:
            tokens = [sot_token] + tokenizer.encode(text) + [eot_token]
        except KeyError:
            tokens = [sot_token, eot_token]

        result = np.zeros(context_length, dtype=np.int32)
        if len(tokens) > context_length:
            tokens = tokens[:context_length]
            tokens[-1] = eot_token
        result[: len(tokens)] = tokens
        all_tokens.append(result)

    return np.array(all_tokens)
