.. ---------------------------------------------------------------------------
.. Copyright 2016 Nervana Systems Inc.
.. Licensed under the Apache License, Version 2.0 (the "License");
.. you may not use this file except in compliance with the License.
.. You may obtain a copy of the License at
..
..      http://www.apache.org/licenses/LICENSE-2.0
..
.. Unless required by applicable law or agreed to in writing, software
.. distributed under the License is distributed on an "AS IS" BASIS,
.. WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
.. See the License for the specific language governing permissions and
.. limitations under the License.
.. ---------------------------------------------------------------------------

Caffe
=====

In ngraph, we aim to provide utilities that enable frontend interoperability
with other frameworks such as `caffe <http://caffe.berkeleyvision.org/>`__.
The caffe importer allows users to build a graph of ngraph ops from the layers in
model prototxt. This graph can be executed using ngraph transformers.

Sum Example
-----------
Here's a sample sum example for the caffe importer.
Sample prototxt is given below to compute the operation **D = A+B+C**

::

    name: "Sum"
    layer {
        name: "A"
        type: "DummyData"
        top: "A"
        dummy_data_param {
            data_filler {
                type: "constant"
                value: 1.0
            }
            shape {
                dim:2
                dim:3
            }
        }
    }

    layer {
        name: "B"
        type: "DummyData"
        top: "B"
        dummy_data_param {
            data_filler {
                type: "constant"
                value: 3.0
            }
            shape {
                dim:2
                dim: 3
            }
        }
    }

    layer {
        name: "C"
        type: "DummyData"
        top: "C"
        dummy_data_param {
            data_filler {
                type: "constant"
                value: -2.0
            }
            shape {
                dim:2
                dim:3 
            }
        }
    }

    layer {
        name: "D"
        type: "Eltwise"
        top: "D"
        bottom: "A"
        bottom: "B"
        bottom: "C"
        eltwise_param {
            operation: SUM
        }
    }


**Sample code to compute D in the above prototxt using the python script**

::

    from __future__ import print_function
    import ngraph.transformers as ngt
    from ngraph.frontends.caffe.cf_importer.importer import parse_prototxt

    model = "sum.prototxt"
    op_map = parse_prototxt(model,verbose=True)
    op = op_map.get("D")
    res = ngt.make_transformer().computation(op)()
    print("Result is:",res)

**Explanation:**

::

    from ngraph.frontends.caffe.cf_importer.importer import parse_prototxt

        - This will import the parsing function

::

    model = "sum.prototxt"
    op_map = parse_prototxt(model,verbose=True)

        - parse_prototxt() will read the prototxt and outputs a graph. 

::

    op = op_map.get("D")

        - ngraph op of any layer can be obtained from the get() function on the graph

::

    res = ngt.make_transformer().computation(op)()

        - after getting the ngraph of required layer, it can be executed using ngrpah tranformers

Command Line interface
-----------------------

caffe like Command line interface is also available to run the prototxt as given below:

::

    python importer.py compute -model  sum.prototxt -name C,D,A 

Limitations
------------

Currently only sum operation on dummy data can be executed. Stay tuned for more functionality

