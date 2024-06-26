'''
train process, still have some problems
'''
import time
import pickle as pkl
from typing import Tuple, Callable, List, TypedDict

import numpy as np
import torch
from torch import nn as nn
from torch import optim, Tensor
from torch.utils.data import DataLoader
from tqdm import tqdm

# local import
from dataset import TextDataset, Tokenizer
from model.Transformer import TransformerModel
from model.mask import TransformerMasking
from config import *
from utils import get_rouge


LossFn = Callable[[Tensor, Tensor], Tensor]


# Hyperparameters
# DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
DEVICE = torch.device("cpu")

EPOCHS = 10
LEARNING_RATE = 1e-3
BATCH_SIZE = 64


class HistoryDict(TypedDict):
    train_loss: List[float]
    val_loss: List[float]


def train_step(
    model: torch.nn.Module,
    enc_x: Tensor, dec_x: Tensor, y,
    src_mask: Tensor, tgt_mask: Tensor,
    src_padding_mask: Tensor, tgt_padding_mask: Tensor,
    optimizer: torch.optim.Optimizer,
    loss_fn: LossFn
) -> float:
    model.train()
    optimizer.zero_grad()
    logits = model(enc_x, dec_x, src_mask, tgt_mask,
                   src_padding_mask, tgt_padding_mask)
    # (batch_size * seq_len, n_token)
    logits = logits.view(-1, logits.size(-1))
    y = y.view(-1).long()  # (batch_size * seq_len)
    # 将y转化为one-hot编码
    y = nn.functional.one_hot(y, num_classes=logits.size(-1)).float()
    loss = loss_fn(logits, y)
    loss.backward()
    optimizer.step()
    return loss.item()


@torch.no_grad()
def val_step(
    model: torch.nn.Module,
    enc_x: Tensor, dec_x: Tensor, y,
    src_mask: Tensor, tgt_mask: Tensor,
    src_padding_mask: Tensor, tgt_padding_mask: Tensor,
    loss_fn: LossFn
) -> float:
    model.eval()
    logits = model(enc_x, dec_x, src_mask, tgt_mask,
                   src_padding_mask, tgt_padding_mask)
    # (batch_size * seq_len, n_token)
    logits = logits.view(-1, logits.size(-1))
    y = y.view(-1).long()
    # 将y转化为one-hot编码
    y = nn.functional.one_hot(y, num_classes=logits.size(-1)).float()
    loss = loss_fn(logits, y)
    return loss.item()


def train(
    model: torch.nn.Module,
    train_loader: DataLoader,
    val_loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    *,
    device: torch.device = DEVICE,
    loss_fn: LossFn = nn.CrossEntropyLoss(),
    max_epochs: int = EPOCHS,
    early_stopping: int = 3,
    print_every: int = 3,
    save_dir: str = None,
    verbose: bool = True
) -> HistoryDict:
    history = {
        "train_loss": [],
        "val_loss": [],
    }
    start_time = time.time()
    for epoch in range(max_epochs):
        running_loss = 0
        for i, (enc_x, dec_x, y) in tqdm(enumerate(train_loader), total=len(train_loader)):
            # x: (batch_size, seq_len), y: (batch_size, seq_len)
            enc_x, dec_x, y = enc_x.to(device), dec_x.to(device), y.to(device)
            src_mask = None
            tgt_mask = TransformerMasking._generate_square_subsequent_mask(
                dec_x.size(1)).to(device)
            src_padding_mask = TransformerMasking._generate_padding_mask(
                enc_x, PAD_NUM).to(device)
            tgt_padding_mask = TransformerMasking._generate_padding_mask(
                dec_x, PAD_NUM).to(device)
            loss = train_step(
                model, enc_x, dec_x, y, src_mask, tgt_mask, src_padding_mask, tgt_padding_mask, optimizer, loss_fn)
            running_loss += loss
        train_loss = running_loss / (i + 1)
        val_running_loss = 0
        for i, (enc_x, dec_x, y) in tqdm(enumerate(val_loader), total=len(val_loader)):
            enc_x, dec_x, y = enc_x.to(device), dec_x.to(device), y.to(device)
            src_mask = None
            tgt_mask = TransformerMasking._generate_square_subsequent_mask(
                dec_x.size(1)).to(device)
            src_padding_mask = TransformerMasking._generate_padding_mask(
                enc_x, PAD_NUM).to(device)
            tgt_padding_mask = TransformerMasking._generate_padding_mask(
                dec_x, PAD_NUM).to(device)

            loss = val_step(
                model, enc_x, dec_x, y, src_mask, tgt_mask, src_padding_mask, tgt_padding_mask, loss_fn)
            val_running_loss += loss
        val_loss = val_running_loss / (i + 1)
        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)

        # early stopping
        if epoch > early_stopping and val_loss > np.mean(history["val_loss"][-(early_stopping + 1): -1]):
            if verbose:
                print(f"Early stopping at epoch {epoch}")
            break
        if verbose and epoch % print_every == 0:
            print(f"---Epoch {epoch+1}/{max_epochs}")
            print(
                f"Train Loss: {train_loss:.4f} | Val Loss: {val_loss:.4f}")
        torch.cuda.empty_cache()

    end_time = time.time()
    if verbose:
        print(f"Training time: {end_time - start_time:.2f} seconds")
        print(f"\n-----At last, Epoch: {epoch}\n----------")
        print(f"Train loss: {loss:.4f}   | Val loss: {val_loss:.4f}")

    if save_dir is not None:
        if not os.path.exists(os.path.dirname(save_dir)):
            os.makedirs(os.path.dirname(save_dir))
        save_path = save_dir + "model.pth"
        torch.save(model.state_dict(), save_path)
        print(f"Model saved at {save_path}")
    return history


def generate(
        test_loader: DataLoader,
        model: torch.nn.Module,
        generate_len: int = SUMMARY_THRESHOLD,
        *,
        device: torch.device = DEVICE,
) -> List[str]:

    model.eval()
    generated_summaries = []
    for i, enc_x in enumerate(test_loader):
        enc_x = enc_x.to(device)
        src_mask = None
        src_padding_mask = TransformerMasking._generate_padding_mask(
            enc_x, PAD_NUM).to(device)

        generated = model.generate(
            src=enc_x, src_mask=src_mask,
            generate_len=generate_len,
            src_key_padding_mask=src_padding_mask)  # shape: (batch_size, seq_len)
        generated_summaries.append(generated.reshape(-1).tolist())
    return generated_summaries


def plot_loss(history: HistoryDict):
    import matplotlib.pyplot as plt
    plt.plot(history["train_loss"], label="Train Loss")
    plt.plot(history["val_loss"], label="Val Loss")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.legend()
    plt.show()


if __name__ == "__main__":
    with open(os.path.join(DATA_DIR, "word2idx.pkl"), "rb") as f:
        word2idx = pkl.load(f)
    with open(os.path.join(DATA_DIR, "idx2word.pkl"), "rb") as f:
        idx2word = pkl.load(f)
    tokenizer = Tokenizer(word2idx, idx2word)
    train_dataset = TextDataset(TRAIN_FLAG, tokenizer=tokenizer)
    val_dataset = TextDataset(VAL_FLAG, tokenizer=tokenizer)
    test_dataset = TextDataset(TEST_FLAG, tokenizer=tokenizer)
    train_loader = DataLoader(
        train_dataset, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(
        val_dataset, batch_size=BATCH_SIZE, shuffle=False)
    test_loader = DataLoader(
        test_dataset, batch_size=BATCH_SIZE, shuffle=False)

    model = TransformerModel(n_token=VOCAB_SIZE, d_model=128, n_head=8,
                             encoder_layers=4, decoder_layers=4, n_hid=256).to(DEVICE)
    OUT_DIR = "./output"
    model_path = os.path.join(OUT_DIR, "model.pth")
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path))
        history_path = os.path.join(OUT_DIR, "history.pkl")
        with open(history_path, "rb") as f:
            history = pkl.load(f)
    else:
        optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)
        history = train(model, train_loader, val_loader, optimizer, device=DEVICE,
                        max_epochs=5, early_stopping=3, print_every=1, save_dir=OUT_DIR)
        # 存储history
        with open(OUT_DIR + "history.pkl", "wb") as f:
            pkl.dump(history, f)

    generated_summaries = generate(
        test_loader=test_loader, model=model)
    result_path = os.path.join(RESULT_DIR, "result.csv")
    for idx, summary in enumerate(generated_summaries):
        summary_str = tokenizer.decode(summary)
        with open(result_path, "a") as f:
            f.write(f"{idx} {summary_str}\n")

    plot_loss(history)
