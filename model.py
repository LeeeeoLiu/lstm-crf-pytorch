import torch
import torch.nn as nn
from torch.autograd import Variable as Var

BATCH_SIZE = 16
EMBED_SIZE = 100
HIDDEN_SIZE = 1000
NUM_LAYERS = 2
DROPOUT = 0.5
BIDIRECTIONAL = True
NUM_DIRS = 2 if BIDIRECTIONAL else 1
LEARNING_RATE = 0.01
WEIGHT_DECAY = 1e-4

SOS = "<SOS>"
EOS = "<EOS>"
PAD = "<PAD>"

torch.manual_seed(1)
CUDA = torch.cuda.is_available()

class lstm_crf(nn.Module):

    def __init__(self, vocab_size, tag_to_idx):
        super(lstm_crf, self).__init__()
        self.tag_to_idx = tag_to_idx
        self.tagset_size = len(tag_to_idx)
        self.seq_len = [] # sequence lengths

        # architecture
        self.embed = nn.Embedding(vocab_size, EMBED_SIZE, padding_idx = 0)
        self.lstm = nn.LSTM( \
            input_size = EMBED_SIZE, \
            hidden_size = HIDDEN_SIZE // NUM_DIRS, \
            num_layers = NUM_LAYERS, \
            bias = True, \
            batch_first = True, \
            dropout = DROPOUT, \
            bidirectional = BIDIRECTIONAL \
        )
        self.hidden_to_tags = nn.Linear(HIDDEN_SIZE, self.tagset_size) # LSTM output to tags

        # matrix of transition scores from j to i
        self.trans = nn.Parameter(randn(self.tagset_size, self.tagset_size))
        self.trans.data[tag_to_idx[SOS], :] = -10000. # no transition to SOS
        self.trans.data[:, tag_to_idx[EOS]] = -10000. # no transition from EOS except to PAD
        self.trans.data[:, tag_to_idx[PAD]] = -10000. # no transition from PAD except to PAD
        self.trans.data[tag_to_idx[PAD], :] = -10000. # no transition to PAD except from EOS
        self.trans.data[tag_to_idx[PAD], tag_to_idx[EOS]] = 0.
        self.trans.data[tag_to_idx[PAD], tag_to_idx[PAD]] = 0.

    def init_hidden(self): # initialize hidden states
        h1 = Var(randn(NUM_LAYERS * NUM_DIRS, BATCH_SIZE, HIDDEN_SIZE // NUM_DIRS))
        h2 = Var(randn(NUM_LAYERS * NUM_DIRS, BATCH_SIZE, HIDDEN_SIZE // NUM_DIRS))
        return (h1, h2)

    def lstm_forward(self, x): # LSTM forward pass
        self.hidden = self.init_hidden()
        self.seq_len = [len_unpadded(seq) for seq in x]
        embed = self.embed(x)
        embed = nn.utils.rnn.pack_padded_sequence(embed, self.seq_len, batch_first = True)
        y, self.hidden = self.lstm(embed, self.hidden)
        y, _ = nn.utils.rnn.pad_packed_sequence(y, batch_first = True)
        # y = y.contiguous().view(-1, HIDDEN_SIZE)
        y = self.hidden_to_tags(y)
        # y = y.view(BATCH_SIZE, -1, self.tagset_size)
        return y

    def crf_score(self, y, y0):
        score = Var(Tensor(BATCH_SIZE).fill_(0.))
        y0 = torch.cat([LongTensor(BATCH_SIZE, 1).fill_(self.tag_to_idx[SOS]), y0], 1)
        for b in range(len(self.seq_len)):
            for t in range(self.seq_len[b]): # iterate through the sentence
                emit_score = y[b, t, y0[b, t + 1]]
                trans_score = self.trans[y0[b, t + 1], y0[b, t]]
                score[b] = score[b] + emit_score + trans_score
        return score

    def crf_score_batch(self, y, y0, mask):
        score = Var(Tensor(BATCH_SIZE).fill_(0.))
        y0 = torch.cat([LongTensor(BATCH_SIZE, 1).fill_(self.tag_to_idx[SOS]), y0], 1)
        for t in range(y.size(1)): # iterate through the sentence
            mask_t = Var(mask[:, t])
            emit_score = torch.cat([y[b, t, y0[b, t + 1]] for b in range(BATCH_SIZE)])
            trans_score = torch.cat([self.trans[seq[t + 1], seq[t]] for seq in y0]) * mask_t
            score = score + emit_score + trans_score
        return score

    def crf_forward(self, y): # forward algorithm for CRF
        # initialize forward variables in log space
        score = Tensor(BATCH_SIZE, self.tagset_size).fill_(-10000.)
        score[:, self.tag_to_idx[SOS]] = 0.
        score = Var(score)
        for b in range(len(self.seq_len)):
            for t in range(self.seq_len[b]): # iterate through the sentence
                score_t = [] # forward variables at this timestep
                for f in range(self.tagset_size): # for each next tag
                    emit_score = y[b, t, f].expand(self.tagset_size)
                    trans_score = self.trans[f].expand(self.tagset_size)
                    z = log_sum_exp(score[b] + emit_score + trans_score)
                    score_t.append(z)
                score[b] = torch.cat(score_t)
        score = torch.cat([log_sum_exp(i) for i in score]) # partition function
        return score

    def crf_forward_batch(self, y, mask): # forward algorithm for CRF
        # initialize forward variables in log space
        score = Tensor(BATCH_SIZE, self.tagset_size).fill_(-10000.)
        score[:, self.tag_to_idx[SOS]] = 0.
        score = Var(score)
        for t in range(y.size(1)): # iterate through the sentence
            score_t = [] # forward variables at this timestep
            len_t = int(torch.sum(mask[:, t])) # masked batch length
            for f in range(self.tagset_size): # for each next tag
                emit_score = torch.cat([y[b, t, f].expand(1, self.tagset_size) for b in range(len_t)])
                trans_score = self.trans[f].expand(len_t, self.tagset_size)
                z = log_sum_exp_batch2(score, emit_score + trans_score)
                score_t.append(z)
            score = torch.cat(score_t, 1)
        score = log_sum_exp_batch1(score).view(BATCH_SIZE) # partition function
        return score

    def viterbi(self, y):
        # initialize backpointers and viterbi variables in log space
        bptr = []
        score = Tensor(self.tagset_size).fill_(-10000.)
        score[self.tag_to_idx[SOS]] = 0.
        score = Var(score)

        for t in range(len(y)): # iterate through the sentence
            # backpointers and viterbi variables at this timestep
            bptr_t = []
            score_t = []
            for i in range(self.tagset_size): # for each next tag
                z = score + self.trans[i]
                best_tag = argmax(z) # find the best previous tag
                bptr_t.append(best_tag)
                score_t.append(z[best_tag])
            bptr.append(bptr_t)
            score = torch.cat(score_t) + y[t]
        best_tag = argmax(score)
        best_score = score[best_tag]

        # back-tracking
        best_path = [best_tag]
        for bptr_t in reversed(bptr):
            best_path.append(bptr_t[best_tag])
        best_path = reversed(best_path[:-1])

        return best_path

    def loss(self, x, y0):
        y = self.lstm_forward(x)
        '''
        # iterative training
        score = self.crf_score(y, y0)
        Z = self.crf_forward(y)
        '''
        # mini-batch training
        mask = x.data.gt(0).float()
        y = y * Var(mask.unsqueeze(-1).expand_as(y))
        score = self.crf_score_batch(y, y0, mask)
        Z = self.crf_forward_batch(y, mask)
        L = torch.mean(Z - score) # negative log probability
        return L

    def forward(self, x): # LSTM-CRF forward for prediction
        result = []
        y = self.lstm_forward(x)
        for i in range(len(self.seq_len)):
            if self.seq_len[i] > 1:
                best_path = self.viterbi(y[i][:self.seq_len[i]])
            else:
                best_path = []
            result.append(best_path)
        return result

def Tensor(*args):
    x = torch.Tensor(*args)
    return x.cuda() if CUDA else x

def LongTensor(*args):
    x = torch.LongTensor(*args)
    return x.cuda() if CUDA else x

def randn(*args):
    x = torch.randn(*args)
    return x.cuda() if CUDA else x

def len_unpadded(x): # get unpadded sequence length
    return next((i for i, j in enumerate(x) if scalar(j) == 0), len(x))

def scalar(x):
    return x.view(-1).data.tolist()[0]

def argmax(x):
    return scalar(torch.max(x, 0)[1]) # for 1D tensor

def log_sum_exp(x):
    max_score = x[argmax(x)]
    max_score_broadcast = max_score.expand_as(x)
    return max_score + torch.log(torch.sum(torch.exp(x - max_score_broadcast)))

def log_sum_exp_batch1(x):
    max_score = torch.cat([i[argmax(i)] for i in x])
    max_score_broadcast = max_score.view(-1, 1).expand_as(x)
    z = max_score + torch.log(torch.sum(torch.exp(x - max_score_broadcast), 1))
    return z

def log_sum_exp_batch2(x, y):
    z = x[:len(y)] + y
    max_score = torch.cat([i[argmax(i)] for i in z])
    max_score_broadcast = max_score.view(-1, 1).expand_as(z)
    z = max_score + torch.log(torch.sum(torch.exp(z - max_score_broadcast), 1))
    if len(x) > len(z):
        z = torch.cat((z, torch.cat([i[argmax(i)] for i in x[len(y):]])))
    return z.view(len(x), 1)
