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

from ngraph.op_graph.op_graph import TensorOp

class BatchnormOp(TensorOp):

    def __init__(self, inputs, gamma, bias, epsilon, mean, variance, **kwargs):
        super(BatchnormOp, self).__init__(args=(inputs, gamma, bias, epsilon, mean, variance), axes=inputs.axes, **kwargs)
        self.eps = epsilon

    def generate_adjoints(self, adjoints, delta, inputs):
        bprop_batchnorm_op = BpropBatchnormOp(delta, inputs, self)
        inputs.generate_add_delta(adjoints, bprop_batchnorm_op)


class BpropBatchnormOp(TensorOp):
    """
    Maintains index and conv_params through forwarding of the original relu.
    
    Arguments:
    fprop: corrosponding batchnormOp.
    delta: global gradients from the previous layer
    inputs: actual input to the batchnormOp
    """
    def __init__(self, inputs, delta, fprop, **kwargs):
        super(BpropBatchnormOp, self).__init__(args=(inputs, delta), axes=delta.axes, **kwargs)
        self.fprop = fprop
