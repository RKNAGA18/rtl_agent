import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from numpy.lib.stride_tricks import sliding_window_view
from skimage.metrics import structural_similarity as ssim

rng = np.random.default_rng(42)

# ----------------------------------------------------------------------
# 1. SYNTHETIC MASK DATASET  (stand-in for real GDSII clips)
# ----------------------------------------------------------------------
PATCH = 24          # patch size (pixels)
N_SAMPLES = 300
N_TRAIN = 240

def make_mask(size=PATCH):
    """Random binary layout patch: mix of contact holes and line/space bars."""
    m = np.zeros((size, size), dtype=np.float32)
    n_feat = rng.integers(2, 6)
    for _ in range(n_feat):
        if rng.random() < 0.5:                      # rectangular contact/via
            h, w = rng.integers(3, 7, size=2)
            y, x = rng.integers(0, size - h), rng.integers(0, size - w)
            m[y:y + h, x:x + w] = 1.0
        else:                                        # line/space bar
            w = rng.integers(2, 4)
            x = rng.integers(0, size - w)
            m[:, x:x + w] = 1.0
    return m

masks = np.stack([make_mask() for _ in range(N_SAMPLES)]).astype(np.float32)

# ----------------------------------------------------------------------
# 2. PHYSICS-BASED LABEL: Hopkins-style partially-coherent imaging
#    approximated as mask convolved with an optical PSF (low-pass kernel).
#    This plays the role of the expensive rigorous simulator whose output
#    the CNN is trained to reproduce.
# ----------------------------------------------------------------------
def gaussian_psf(ksize=7, sigma=1.3):
    ax = np.arange(ksize) - ksize // 2
    xx, yy = np.meshgrid(ax, ax)
    k = np.exp(-(xx**2 + yy**2) / (2 * sigma**2))
    return (k / k.sum()).astype(np.float32)

PSF = gaussian_psf()

def convolve_same(img, kernel):
    kh, kw = kernel.shape
    pad = kh // 2
    padded = np.pad(img, pad, mode="edge")
    windows = sliding_window_view(padded, (kh, kw))
    return np.einsum("ijkl,kl->ij", windows, kernel)

aerial_gt = np.stack([convolve_same(m, PSF) for m in masks]).astype(np.float32)
aerial_gt = (aerial_gt - aerial_gt.min()) / (aerial_gt.max() - aerial_gt.min())  # normalize [0,1]

X_train, X_test = masks[:N_TRAIN], masks[N_TRAIN:]
Y_train, Y_test = aerial_gt[:N_TRAIN], aerial_gt[N_TRAIN:]

# ----------------------------------------------------------------------
# 3. COMPACT CNN:  Conv(1->8,5x5) -ReLU-> Conv(8->1,5x5) -Sigmoid-> output
#    im2col based, fully vectorised forward/backward.
# ----------------------------------------------------------------------
def im2col(X, kh, kw, pad):
    # X: (N, C, H, W) -> cols: (N, H, W, C, kh, kw)
    N, C, H, W = X.shape
    Xp = np.pad(X, ((0, 0), (0, 0), (pad, pad), (pad, pad)), mode="constant")
    windows = sliding_window_view(Xp, (kh, kw), axis=(2, 3))  # (N,C,H,W,kh,kw)
    return np.transpose(windows, (0, 2, 3, 1, 4, 5))          # (N,H,W,C,kh,kw)

class ConvLayer:
    def __init__(self, c_in, c_out, k, act):
        limit = np.sqrt(2.0 / (c_in * k * k))
        self.W = rng.normal(0, limit, size=(c_out, c_in, k, k)).astype(np.float32)
        self.b = np.zeros(c_out, dtype=np.float32)
        self.k, self.pad, self.act = k, k // 2, act
        # Adam state
        self.mW = np.zeros_like(self.W); self.vW = np.zeros_like(self.W)
        self.mb = np.zeros_like(self.b); self.vb = np.zeros_like(self.b)

    def forward(self, X):
        self.X = X
        cols = im2col(X, self.k, self.k, self.pad)          # (N,H,W,Cin,k,k)
        self.cols = cols
        z = np.einsum("nhwckl,ockl->nohw", cols, self.W) + self.b[None, :, None, None]
        self.z = z
        if self.act == "relu":
            self.a = np.maximum(z, 0)
        elif self.act == "sigmoid":
            self.a = 1 / (1 + np.exp(-z))
        return self.a

    def backward(self, dA, lr, t, beta1=0.9, beta2=0.999, eps=1e-8):
        if self.act == "relu":
            dZ = dA * (self.z > 0)
        elif self.act == "sigmoid":
            dZ = dA * self.a * (1 - self.a)
        N = dZ.shape[0]
        dW = np.einsum("nohw,nhwckl->ockl", dZ, self.cols) / N
        db = dZ.sum(axis=(0, 2, 3)) / N
        # dX = full convolution of dZ with the 180-degree-rotated kernel
        # (standard CNN backprop identity for 'same' padding, stride 1)
        Wf = self.W[:, :, ::-1, ::-1]
        dZp = np.pad(dZ, ((0, 0), (0, 0), (self.pad, self.pad), (self.pad, self.pad)))
        cols_dz = im2col(dZp, self.k, self.k, 0)  # (N,H,W,Cout,k,k), input already padded
        dX = np.einsum("nhwokl,ockl->nchw", cols_dz, Wf)

        # Adam update
        self.mW = beta1 * self.mW + (1 - beta1) * dW
        self.vW = beta2 * self.vW + (1 - beta2) * dW**2
        mW_hat = self.mW / (1 - beta1**t); vW_hat = self.vW / (1 - beta2**t)
        self.W -= lr * mW_hat / (np.sqrt(vW_hat) + eps)

        self.mb = beta1 * self.mb + (1 - beta1) * db
        self.vb = beta2 * self.vb + (1 - beta2) * db**2
        mb_hat = self.mb / (1 - beta1**t); vb_hat = self.vb / (1 - beta2**t)
        self.b -= lr * mb_hat / (np.sqrt(vb_hat) + eps)
        return dX

conv1 = ConvLayer(c_in=1, c_out=8, k=5, act="relu")
conv2 = ConvLayer(c_in=8, c_out=1, k=5, act="sigmoid")

def forward(X):
    a1 = conv1.forward(X[:, None, :, :])
    a2 = conv2.forward(a1)
    return a2[:, 0]

def train_step(Xb, Yb, lr, t):
    pred = forward(Xb)
    err = pred - Yb
    loss = np.mean(err**2)
    dA2 = (2.0 / Yb.size) * err[:, None, :, :]
    dA1 = conv2.backward(dA2, lr, t)
    conv1.backward(dA1, lr, t)
    return loss

# ----------------------------------------------------------------------
# 4. TRAINING LOOP
# ----------------------------------------------------------------------
EPOCHS = 250
BATCH = 30
LR = 0.05
train_hist, test_hist = [], []

for epoch in range(1, EPOCHS + 1):
    idx = rng.permutation(N_TRAIN)
    epoch_loss = 0.0
    for b in range(0, N_TRAIN, BATCH):
        bi = idx[b:b + BATCH]
        epoch_loss += train_step(X_train[bi], Y_train[bi], LR, epoch) * len(bi)
    train_hist.append(epoch_loss / N_TRAIN)
    test_pred = forward(X_test)
    test_hist.append(np.mean((test_pred - Y_test) ** 2))

# ----------------------------------------------------------------------
# 5. EVALUATION METRICS
# ----------------------------------------------------------------------
pred_test = forward(X_test)
rmse = np.sqrt(np.mean((pred_test - Y_test) ** 2))
mae = np.mean(np.abs(pred_test - Y_test))
ssim_vals = [ssim(Y_test[i], pred_test[i], data_range=1.0) for i in range(len(X_test))]
mean_ssim = np.mean(ssim_vals)

print(f"Final Train MSE : {train_hist[-1]:.5f}")
print(f"Final Test  MSE : {test_hist[-1]:.5f}")
print(f"Test RMSE        : {rmse:.5f}")
print(f"Test MAE         : {mae:.5f}")
print(f"Mean SSIM (test) : {mean_ssim:.4f}")

# ----------------------------------------------------------------------
# 6. PLOTS
# ----------------------------------------------------------------------
plt.rcParams.update({"font.size": 10})

# (a) Loss convergence
fig, ax = plt.subplots(figsize=(6, 4))
ax.plot(train_hist, label="Train MSE", lw=2)
ax.plot(test_hist, label="Test MSE", lw=2, linestyle="--")
ax.set_xlabel("Epoch"); ax.set_ylabel("MSE Loss")
ax.set_title("Loss Convergence — Mask → Aerial Image CNN (Adam)")
ax.legend(); ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("/home/claude/work/fig_loss_convergence.png", dpi=150)
plt.close(fig)

# (b) Qualitative predictions: mask / ground truth / CNN prediction
fig, axes = plt.subplots(3, 4, figsize=(10, 7.5))
for row in range(3):
    i = row
    axes[row, 0].imshow(X_test[i], cmap="gray"); axes[row, 0].set_title(f"Mask #{i+1}")
    axes[row, 1].imshow(Y_test[i], cmap="inferno"); axes[row, 1].set_title("Ground-truth\nAerial Image")
    axes[row, 2].imshow(pred_test[i], cmap="inferno"); axes[row, 2].set_title("CNN-Predicted\nAerial Image")
    diff = np.abs(Y_test[i] - pred_test[i])
    im = axes[row, 3].imshow(diff, cmap="viridis", vmin=0, vmax=0.3)
    axes[row, 3].set_title(f"|Error|\nSSIM={ssim_vals[i]:.3f}")
    for c in range(4):
        axes[row, c].axis("off")
fig.suptitle("Qualitative Results on Held-out Test Patches", y=1.0)
fig.tight_layout()
fig.savefig("/home/claude/work/fig_predictions.png", dpi=150)
plt.close(fig)

# (c) Convolution-kernel demonstration (single patch, single filter)
sample_mask = X_test[0]
learned_filter0 = conv1.W[0, 0]           # first learned 5x5 kernel of conv1
manual_conv = convolve_same(sample_mask, PSF)
fig, axes = plt.subplots(1, 3, figsize=(9, 3.2))
axes[0].imshow(sample_mask, cmap="gray"); axes[0].set_title("Input Mask Patch"); axes[0].axis("off")
axes[1].imshow(PSF, cmap="viridis"); axes[1].set_title("Physics PSF Kernel\n(ground-truth label generator)"); axes[1].axis("off")
axes[2].imshow(learned_filter0, cmap="viridis"); axes[2].set_title("CNN Learned Kernel\n(conv1, filter #1)"); axes[2].axis("off")
fig.tight_layout()
fig.savefig("/home/claude/work/fig_kernel_compare.png", dpi=150)
plt.close(fig)

# (d) Activation function comparison
z = np.linspace(-6, 6, 300)
relu = np.maximum(0, z)
sigmoid = 1 / (1 + np.exp(-z))
tanh = np.tanh(z)
fig, ax = plt.subplots(figsize=(6, 4))
ax.plot(z, relu, label="ReLU (hidden layers)", lw=2)
ax.plot(z, sigmoid, label="Sigmoid (output layer)", lw=2)
ax.plot(z, tanh, label="Tanh (reference)", lw=2)
ax.axhline(0, color="grey", lw=0.5); ax.axvline(0, color="grey", lw=0.5)
ax.set_xlabel("z (pre-activation)"); ax.set_ylabel("activation output")
ax.set_title("Activation Function Comparison")
ax.legend(); ax.grid(alpha=0.3)
fig.tight_layout()
fig.savefig("/home/claude/work/fig_activation_compare.png", dpi=150)
plt.close(fig)

print("Saved: fig_loss_convergence.png, fig_predictions.png, fig_kernel_compare.png, fig_activation_compare.png")

with open("/home/claude/work/metrics.txt", "w") as f:
    f.write(f"Final Train MSE : {train_hist[-1]:.5f}\n")
    f.write(f"Final Test  MSE : {test_hist[-1]:.5f}\n")
    f.write(f"Test RMSE        : {rmse:.5f}\n")
    f.write(f"Test MAE         : {mae:.5f}\n")
    f.write(f"Mean SSIM (test) : {mean_ssim:.4f}\n")