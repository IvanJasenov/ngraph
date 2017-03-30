# ----------------------------------------------------------------------------
# Copyright 2016 Nervana Systems Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------------

from __future__ import division
from __future__ import print_function
import ctypes
import os
import sys
import itertools as itt
import numpy as np

import ctypes as ct
import numpy.ctypeslib as npct


def mkldnn_init(self, engine_path):
    self.mkldnn_enabled = False
    self.mkldnn_engine_initialized = False
    self.mkldnn_verbose = False
    try:
        self.mkldnn_engine_dll = ctypes.CDLL(engine_path)
        self.mkldnn_enabled = True
    except:
        if (os.getenv('MKL_TEST_ENABLE', False)):
            print("Could not load MKLDNN Engine: ", engine_path, "Exiting...")
            sys.exit(1)
        else:
            print("Could not load MKLDNN Engine: ", engine_path, " Will default to numpy")
            return
    if (self.mkldnn_enabled):
        self.init_mkldnn_engine_fn = self.mkldnn_engine_dll.init_mkldnn_engine
        self.init_mkldnn_engine_fn.restype = ctypes.c_void_p
        self.create_mkldnn_conv_fprop_primitives_fn = \
            self.mkldnn_engine_dll.create_mkldnn_conv_fprop_primitives
        self.create_mkldnn_conv_fprop_primitives_fn.argtypes = \
            [ctypes.c_void_p,
             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
             ctypes.c_int, ctypes.c_int,
             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
             ctypes.c_void_p,
             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
             ctypes.c_void_p,
             ctypes.c_void_p, ctypes.c_void_p]
        self.create_mkldnn_conv_fprop_primitives_fn.restype = ctypes.c_void_p
        self.create_mkldnn_conv_bprop_primitives_fn = \
            self.mkldnn_engine_dll.create_mkldnn_conv_bprop_primitives
        self.create_mkldnn_conv_bprop_primitives_fn.argtypes = \
            [ctypes.c_void_p,
             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
             ctypes.c_int, ctypes.c_int,
             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
             ctypes.c_void_p,
             ctypes.c_void_p, ctypes.c_void_p]
        self.create_mkldnn_conv_bprop_primitives_fn.restype = ctypes.c_void_p
        self.run_mkldnn_netlist_fn = self.mkldnn_engine_dll.run_mkldnn_netlist
        self.run_mkldnn_netlist_fn.argtypes = [ctypes.c_void_p]
        self.cleanup_mkldnn_fn = self.mkldnn_engine_dll.cleanup_mkldnn
        self.cleanup_mkldnn_fn.argtypes = [ctypes.c_void_p]
        self.destroy_mkldnn_engine_fn = self.mkldnn_engine_dll.destroy_mkldnn_engine
        self.destroy_mkldnn_engine_fn.argtypes = [ctypes.c_void_p]


def mkldnn_engine_init(self):
    if (self.mkldnn_enabled):
        self.mkldnn_engine = self.init_mkldnn_engine_fn()
        self.mkldnn_engine_initialized = True
        self.mkldnn_conv_fprop_netlist = dict()
        self.mkldnn_conv_bprop_netlist = dict()


def mkldnn_engine_cleanup(self):
    if (self.mkldnn_engine_initialized):
        for i in self.mkldnn_conv_fprop_netlist:
            self.cleanup_mkldnn_fn(self.mkldnn_conv_fprop_netlist[i])
        for i in self.mkldnn_conv_bprop_netlist:
            self.cleanup_mkldnn_fn(self.mkldnn_conv_bprop_netlist[i])
        self.destroy_mkldnn_engine_fn(self.mkldnn_engine)
        self.mkldnn_engine_initialized = False


def init_conv_fprop(self, index, I, F, O, pad, stride):
    if (self.mkldnn_enabled):
        C, D, H, W, N = I.shape
        if (self.mkldnn_verbose):
            print("C,D,H,W,N", C, D, H, W, N)
            print("Input: ", hex(I.ctypes.data), I.shape)
            print("Filter: ", hex(F.ctypes.data), F.shape)
            print("Output: ", hex(O.ctypes.data), O.shape)
            print("Stride: ", stride, len(stride))
            print("Pad: ", pad, len(pad))
        # Only 2D convolution supported in MKLDNN for now
        if (D != 1):
            return
        # Only single precision float supported for now
        if ((I.dtype != np.float32) or (O.dtype != np.float32)):
            return
        # Sanity check tensor shapes
        if ((len(I.shape) != 5) or (len(F.shape) != 5) or
                (len(O.shape) != 5) or (len(stride) != 3) or
                (len(pad) != 3)):
            return
        # NumPy Tensors need to be contiguous
        if (not (I.flags['C_CONTIGUOUS'] and
                 F.flags['C_CONTIGUOUS'] and
                 O.flags['C_CONTIGUOUS'])):
            return
        input_shape = ((ctypes.c_int) * len(I.shape))(*I.shape)
        filter_shape = ((ctypes.c_int) * len(F.shape))(*F.shape)
        output_shape = ((ctypes.c_int) * len(O.shape))(*O.shape)
        pad_data = ((ctypes.c_int) * len(pad))(*pad)
        stride_data = ((ctypes.c_int) * len(stride))(*stride)
        self.mkldnn_conv_fprop_netlist[index] = \
            self.create_mkldnn_conv_fprop_primitives_fn(
                self.mkldnn_engine,
                len(I.shape), len(F.shape),
                1, len(O.shape), len(stride),
                len(pad),
                input_shape, filter_shape,
                None, output_shape,
                I.ctypes.data, F.ctypes.data,
                None, O.ctypes.data,
                stride_data, pad_data)


def fprop_conv(self, index, conv_slices, I, F, O):
    if (self.mkldnn_enabled and index in self.mkldnn_conv_fprop_netlist):
        self.run_mkldnn_netlist_fn(self.mkldnn_conv_fprop_netlist[index])
    else:
        mSlice, pSlice, qSlice, _, _, _ = conv_slices
        K, M, P, Q, N = O.shape

        for (m, mS), (p, pS), (q, qS) in itt.product(enumerate(mSlice),
                                                     enumerate(pSlice),
                                                     enumerate(qSlice)):
            sliceT, sliceD, _ = mS
            sliceR, sliceH, _ = pS
            sliceS, sliceW, _ = qS
            slicedF = F[:, sliceT, sliceR, sliceS, :].reshape((-1, K))
            slicedI = I[:, sliceD, sliceH, sliceW, :].reshape((-1, N))
            O[:, m, p, q, :] = np.dot(slicedF.T, slicedI)


def init_conv_bprop(self, index, E, F, gI, pad, stride):
    if (self.mkldnn_enabled):
        C, D, H, W, N = E.shape
        if (self.mkldnn_verbose):
            print("MKL INIT CONV BPROP index: ", index,
                  " E.shape: ", E.shape, " F.shape: ", F.shape,
                  " gI.shape: ", gI.shape, " Stride: ", stride,
                  " Pad: ", pad)
        # Only 2D convolution supported in MKLDNN for now
        if (D != 1):
            return
        # Only single precision float supported for now
        if ((E.dtype != np.float32) or (F.dtype != np.float32)):
            return
        # Sanity check tensor shapes
        if ((len(E.shape) != 5) or (len(F.shape) != 5) or
                (len(gI.shape) != 5) or (len(stride) != 3) or
                (len(pad) != 3)):
            return
        # NumPy Tensors need to be contiguous
        if (not (E.flags['C_CONTIGUOUS'] and
                 F.flags['C_CONTIGUOUS'] and
                 gI.flags['C_CONTIGUOUS'])):
            return
        input_shape = ((ctypes.c_int) * len(E.shape))(*E.shape)
        filter_shape = ((ctypes.c_int) * len(F.shape))(*F.shape)
        output_shape = ((ctypes.c_int) * len(gI.shape))(*gI.shape)
        pad_data = ((ctypes.c_int) * len(pad))(*pad)
        stride_data = ((ctypes.c_int) * len(stride))(*stride)
        self.mkldnn_conv_bprop_netlist[index] =\
            self.create_mkldnn_conv_bprop_primitives_fn(
                self.mkldnn_engine,
                len(E.shape), len(F.shape), 1, len(gI.shape), len(stride), len(pad),
                input_shape, filter_shape, None, output_shape,
                E.ctypes.data, F.ctypes.data, None, gI.ctypes.data,
                stride_data, pad_data)


def bprop_conv(self, index, conv_slices, E, F, gI):
    if (self.mkldnn_enabled and index in self.mkldnn_conv_bprop_netlist):
        self.run_mkldnn_netlist_fn(self.mkldnn_conv_bprop_netlist[index])
    else:
        _, _, _, mSlice, pSlice, qSlice = conv_slices
        F = np.transpose(F[:, ::-1, ::-1, ::-1, :], (4, 1, 2, 3, 0)).copy()
        K, M, P, Q, N = gI.shape

        for (m, mS), (p, pS), (q, qS) in itt.product(enumerate(mSlice),
                                                     enumerate(pSlice),
                                                     enumerate(qSlice)):
            sliceT, sliceD, _ = mS
            sliceR, sliceH, _ = pS
            sliceS, sliceW, _ = qS
            slicedF = F[:, sliceT, sliceR, sliceS, :].reshape((-1, K))
            slicedI = E[:, sliceD, sliceH, sliceW, :].reshape((-1, N))
            gI[:, m, p, q, :] = np.dot(slicedF.T, slicedI)


def update_conv(conv_slices, I, E, U):
    mSlice, pSlice, qSlice, _, _, _ = conv_slices
    K, M, P, Q, N = E.shape
    C, _, _, _, K = U.shape
    U.fill(0.0)

    for (m, mS), (p, pS), (q, qS) in itt.product(enumerate(mSlice),
                                                 enumerate(pSlice),
                                                 enumerate(qSlice)):
        sliceT, sliceD, tlen = mS
        sliceR, sliceH, rlen = pS
        sliceS, sliceW, slen = qS
        slicedI = I[:, sliceD, sliceH, sliceW, :].reshape((-1, N))
        slicedE = E[:, m, p, q, :]
        update = np.dot(slicedI, slicedE.T).reshape((C, tlen, rlen, slen, K))
        U[:, sliceT, sliceR, sliceS, :] += update


def fprop_pool(pool_slices, arrI, arrO):
    kSlice, mSlice, pSlice, qSlice, op, arrA = pool_slices
    K, M, P, Q, N = arrO.shape

    for (k, kS), (m, mS), (p, pS), (q, qS) in itt.product(enumerate(kSlice),
                                                          enumerate(mSlice),
                                                          enumerate(pSlice),
                                                          enumerate(qSlice)):
        sliceC, _ = kS
        sliceD, _ = mS
        sliceH, _ = pS
        sliceW, _ = qS

        sliceI = arrI[sliceC, sliceD, sliceH, sliceW, :].reshape(-1, N)
        if op == "max":
            arrA[k, m, p, q, :] = np.argmax(sliceI, axis=0)
            arrO[k, m, p, q, :] = np.max(sliceI, axis=0)
        elif op == "avg":
            arrO[k, m, p, q, :] = np.mean(sliceI, axis=0)
        elif op == "l2":
            arrO[k, m, p, q, :] = np.sqrt(np.sum(np.square(sliceI), axis=0))


def bprop_pool(pool_slices, arrE, arrD):
    kSlice, mSlice, pSlice, qSlice, op, arrA = pool_slices
    arrD[:] = 0
    K, M, P, Q, N = arrE.shape

    for (k, kS), (m, mS), (p, pS), (q, qS) in itt.product(enumerate(kSlice),
                                                          enumerate(mSlice),
                                                          enumerate(pSlice),
                                                          enumerate(qSlice)):
        sliceC, clen = kS
        sliceD, dlen = mS
        sliceH, hlen = pS
        sliceW, wlen = qS

        patch_in = (sliceC, sliceD, sliceH, sliceW, slice(None))
        patch_out = (k, m, p, q, slice(None))
        sliceB = arrD[patch_in].reshape((-1, N))
        if op == "max":
            max_n = arrA[patch_out]
            sliceB[max_n, list(range(N))] += arrE[patch_out]
        elif op == "avg":
            sliceB += arrE[patch_out] * (1.0 / sliceB.shape[0])
        else:
            raise NotImplementedError
        arrD[patch_in] = sliceB.reshape((clen, dlen, hlen, wlen, N))


def fprop_lut(lut, idx, axis, output):
    output[:] = lut.take(idx.astype(int), axis)


def update_lut(error, idx, pad_idx, axis, dW):
    dW[:] = 0
    idx = idx.astype(int)
    unqidx, inv = np.unique(idx, return_inverse=True)
    groups = [np.where(inv == i) for i in range(len(unqidx))]
    for (wrd_id, group) in zip(unqidx, groups):
        if wrd_id != pad_idx:
            if axis == 0:
                dW[wrd_id, :] = np.sum(error.take(group[0], axis=axis), axis=axis)
            else:
                dW[:, wrd_id] = np.sum(error.take(group[0], axis=axis), axis=axis)


def ctc_cpu(acts, lbls, utt_lens, lbl_lens, grads, costs, n_threads=8):
    basepath = os.path.join(os.path.dirname(__file__), "..", "..", "..")
    temp_loc = os.path.join("examples", "deepspeech", "src", "libwarpctc.so")
    libpath = os.path.join(basepath, temp_loc)
    assert os.path.isfile(libpath), ("Expected libwarpctc.so at {} but not found. "
                                     "Try running make").format(libpath)
    ctclib = npct.load_library(libpath, "")
    ctclib.compute_ctc_loss_cpu.restype = int
    ctclib.compute_ctc_loss_cpu.argtypes = [
        npct.ndpointer(dtype=np.float32, ndim=3),
        npct.ndpointer(dtype=np.float32, ndim=3),
        npct.ndpointer(dtype=np.int32, ndim=1),
        npct.ndpointer(dtype=np.int32, ndim=1),
        npct.ndpointer(dtype=np.int32, ndim=1),
        ct.c_int,
        ct.c_int,
        npct.ndpointer(dtype=np.float32, ndim=1),
        ct.c_int]
    max_t, bsz, nout = acts.shape
    utt_lens = utt_lens * max_t / 100
    utt_lens = utt_lens.astype(np.int32)
    costs.fill(0.)
    grads.fill(0.)
    status = ctclib.compute_ctc_loss_cpu(acts,
                                         grads,
                                         lbls.astype(np.int32),
                                         lbl_lens.astype(np.int32),
                                         utt_lens.astype(np.int32),
                                         nout,
                                         bsz,
                                         costs,
                                         n_threads)
    assert status is 0, "warp-ctc run failed"
