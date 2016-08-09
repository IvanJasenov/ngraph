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
from builtins import object, range, zip
from collections import defaultdict
from operator import mul
from functools import reduce
from itertools import combinations
from geon.op_graph.op_graph import ComputationOp, ElementWise, Function, \
    Buffer, ReductionOp, NumPyTensor


class Digraph(object):
    """
    Base class for Directed graph.
    Includes Graphviz visualization, DFS, topsort
    """

    def _graphviz(self, name=''):
        """
        Export the current Digraph to Graphviz

        Args:
            name (str): Name of the resulting graph

        Returns:
            pygraphviz object
        """

        from graphviz import Digraph
        dot = Digraph(name)
        for node, nexts in list(self.successors.items()):
            dot.node(node.id, node.graph_label, node.style)
            for next in nexts:
                dot.node(next.id, next.graph_label, next.style)
                dot.edge(node.id, next.id)
        return dot

    @staticmethod
    def _invert(adjacency):
        """
        Returns the invert of the given adjacency dict (e.g., successors to predecessors)
        """
        result = {x: set() for x in list(adjacency.keys())}
        for x, others in list(adjacency.items()):
            for y in others:
                result[y].add(x)
        return result

    def __init__(self, successors):
        """
        Initialize directed graph from successors dict

        Args:
            successors (dict: op => set(op)): dict that map each op to all its users
        """
        self.successors = successors

    def render(self, fpath, view=True):
        """
        Renders to a graphviz file

        Args:
            fpath (str): file to write too
        """
        self._graphviz().render(fpath, view=view)

    def view(self):
        """ View the graph. Requires pygraphviz """
        self._graphviz().view()

    def dfs(self, fun):
        """
        Performs DFS, applying the provided function to each node

        Args:
            fun (Function): Function to apply to each visited node
        """
        visited = set()

        # Visit single node
        def visit(u, fun):
            if u not in visited:
                vs = self.successors[u]
                for v in sorted(vs, key=lambda x: x.id):
                    if v not in visited:
                        visit(v, fun)
                fun(u)
                visited.add(u)
        # Get output nodes
        for x in sorted(self.inputs, key=lambda x: x.id):
            visit(x, fun)

    @property
    def inputs(self):
        predecessors = Digraph._invert(self.successors)
        return [u for u, vs in iter(list(predecessors.items())) if len(vs) == 0]

    def topsort(self):
        """
        Topological sort of the nodes

        Returns:
            Sorted list of nodes
        """
        result = []
        self.dfs(lambda x: result.insert(0, x))
        return result


class DataFlowGraph(Digraph):
    """
    Class explicitly representing the dataflow graph
    """

    def _fill_successors(self, results):
        """ Walk through provided results to build the successors map"""
        for w in results:
            self.successors[w] |= set()
            for v in w.args:
                self.successors[v].add(w)
                self._fill_successors({v})

    def __init__(self, transformer, results):
        """
        Initialize the dataflow graph

        Args:
            results (dict): Results of the desired computation
        """

        super(DataFlowGraph, self).__init__(defaultdict(set))
        self.transformer = transformer
        self._fill_successors(results)
        self.results = results

    @property
    def instructions(self):
        """ Returns the ordered instructions to execute the dataflow graph """

        return self.topsort()

    def liveness(self):
        """
        Liveness analysis. The goal is to find, at each program point
        (i.e., instruction line number), which tensors need to be in
        memory (because they will be required later on).

        Returns:
            dict (op => set(tensor_description)): Live tensors at each point
        """

        can_do_inplace = lambda x: False
        order = self.instructions
        # Initialize
        liveness = dict((op, set()) for op in order)
        persistent = {x.tensor_description(self.transformer)
                      for x in self.successors if 'persistent' in x.tags}
        results = {x.tensor_description(self.transformer) for x in self.results}
        liveness[order[-1]] = results | persistent
        # Update
        for current, previous in reversed(list(zip(order[1:], order[:-1]))):
            use = {x.tensor_description(self.transformer) for x in current.args}
            defs = {x.tensor_description(self.transformer) for x in current.defs}
            liveness[previous] = use | (liveness[current] - defs)
        # Inplace not possible
        for op in order:
            if not can_do_inplace(op):
                liveness[op] |= {x.tensor_description(self.transformer) for x in op.args}

        # print max([sum(map(lambda x: reduce(mul, x.shapes, 1)*x.dtype.itemsize,
        # l)) for l in liveness.itervalues()])*1024**-2
        return liveness


# Fusion Policies
def never_fusible(op1, op2):
    """
    Default fusion policies: things are not fusible
    """

    return False


def gpu_fusible(transformer, op1, op2):
    """
    Fusion policies for the GPU
    """

    # Only computations can be merged
    if not isinstance(op1, ComputationOp) or not isinstance(op2, ComputationOp):
        return False

    shapes1 = op1.tensor_description(transformer).shape
    shapes2 = op2.tensor_description(transformer).shape
    # Elementwise functions can be merged together if they have the same shapes
    if isinstance(op1, ElementWise) and isinstance(op2, ElementWise) and shapes1 == shapes2:
        return True

    # Reduction following elementwises can be merged
    if isinstance(op1, ElementWise) and isinstance(op2, ReductionOp):
        return True

    # Elementwise following reductions can be merged
    if isinstance(op1, ReductionOp) and isinstance(op2, ElementWise):
        return True

    # Everything else cannot be merged
    return False


class KernelFlowGraph(DataFlowGraph):
    """
    Class representing a fused dataflow graph
    """

    def _graphviz(self, name=''):
        """
        Export fused dataflow to graphviz.
        Involves some hackery to get graphviz to draw edge between subgraphs

        Args:
            name (str): name of the resulting graph

        Returns:
            pygraphgiz object
        """

        predecessors = Digraph._invert(self.successors)
        from graphviz import Digraph as gvDigraph
        dot = gvDigraph(name, graph_attr={
                        'compound': 'true', 'nodesep': '.5', 'ranksep': '.5'})
        leaves = {x for x, y in list(predecessors.items()) if len(y) == 0}
        subgs = {x: x.ops._graphviz('cluster_{}'.format(x.id))
                 for x in self.successors if isinstance(x, Function)}
        # Subgraphs
        for x, sg in list(subgs.items()):
            sg.body.append('color=gray')
            sg.body.append('label={}'.format(x.id))
            dot.subgraph(sg)
        for x in leaves:
            dot.node(x.id, x.graph_label, x.style)
        # Edges
        edges = {(a, b) for a, _ in list(self.successors.items()) for b in _}
        sorts = {x: x.ops.topsort() for x in self.successors if isinstance(x, Function)}
        firsts = {x: sorts[x][0] if isinstance(x, Function) else x for x in self.successors}
        lasts = {x: sorts[x][-1] if isinstance(x, Function) else x for x in self.successors}
        for a, b in edges:
            kw = {}
            if isinstance(a, Function):
                kw['ltail'] = 'cluster_{}'.format(a.id)
            if isinstance(b, Function):
                kw['lhead'] = 'cluster_{}'.format(b.id)
            dot.edge(lasts[a].id, firsts[b].id, **kw)
        return dot

    def _compute_paths(self):
        """
        Computes useful datastructures for fusion analysis

        path_from: maps node v to nodes that have a path from w
        bad_path_from: map node v to nodes that have a bad path from w

        'bad_paths' are paths that can not be merged.
        """

        path_from, bad_path_from = dict(), dict()
        order = self.topsort()
        for v in reversed(order):
            path_from[v] = {v}
            bad_path_from[v] = set()
            for w in self.successors[v]:
                path_from[v] |= path_from[w]
                if self.fusible(v, w):
                    bad_path_from[v] |= bad_path_from[w]
                else:
                    bad_path_from[v] |= path_from[w]
        return path_from, bad_path_from

    def between(self, v, w, path_from):
        """
        Finds all the nodes on any path between v and w

        Args:
            v (operation): start node
            w (operation): end_node
            path_from (dict): maps node v to nodes that have a path from w
        """

        vertices = set()
        worklist = {w}
        worklist |= {x for x in self.successors[v] if w in path_from[x]}
        while worklist:
            # Update worklist
            x = worklist.pop()
            if x != w:
                worklist |= {y for y in self.successors[
                    x] if w in path_from[y]}
            # Add vertices
            vertices |= {x}
        return vertices

    def transfer_edges(self, v, w, dct):
        """
        Transfers edges from a node into another

        Args:
            v (operation): node that receives edges
            w (operation): node that loses edges
        """

        dct[v] |= dct.pop(w, set()) - {v}
        for node, connected in list(dct.items()):
            if w in connected:
                connected.remove(w)
                if node != v:
                    connected.add(v)

    def __init__(self, dataflow, fusible=never_fusible):
        """
        Performs fusion on the provided dataflow graph

        Implementation of: *Fast Greedy Weighted Fusion*, Ken Kennedy,
        Internal journal of Parallel Programming (2002):
        Download: http://citeseerx.ist.psu.edu/viewdoc
                        /download?doi=10.1.1.95.2695&rep=rep1&type=pdf
        """

        # Extracts clusters
        self.fusible = fusible
        super(KernelFlowGraph, self).__init__(dataflow.results)
        successors = self.successors
        path_from, bad_path_from = self._compute_paths()
        edges = {(a, b) for a, _ in successors.items() for b in _}
        edges = sorted(edges, key=lambda x: (x[0].id, x[1].id))
        clusters = dict((x, {x}) for e in edges for x in e)
        while edges:
            # Pop edges and adjusts order if necessary
            v, w = edges.pop()
            # Cannot be fused
            if w in bad_path_from[v]:
                continue
            # Merge vertices between v and w
            to_merge = self.between(v, w, path_from)
            for x in to_merge:
                clusters[v] |= clusters.pop(x)
                self.transfer_edges(v, x, successors)
                self.transfer_edges(v, x, path_from)
                self.transfer_edges(v, x, bad_path_from)
            edges = {(a, b) for a, _ in successors.items() for b in _}
            edges = sorted(edges, key=lambda x: (x[0].id, x[1].id))
        # Creates adjacency list for each cluster
        extract_subgraph = lambda R: dict(
            (a, b & R) for a, b in list(dataflow.successors.items()) if a in R)
        clusters = {x: extract_subgraph(y) for x, y in list(clusters.items())}
        # Creates final adjacency list
        clusters = {x: Function(y) if isinstance(
            x, ComputationOp) else x for x, y in list(clusters.items())}
        self.successors = {
            clusters[a]: {
                clusters[b] for b in lst} for a,
            lst in list(
                successors.items())}
        # Saves dataflow for visualization
        self.dataflow = dataflow


class UndirectedGraph(object):
    """
    Base class for Undirected graph.
    Includes Graphviz visualization
    """

    def __init__(self, neighbors):
        self.neighbors = neighbors

    def _graphviz(self, name=''):
        from graphviz import Graph
        dot = Graph()
        processed = set()
        for na, _ in list(self.neighbors.items()):
            dot.node(na.id, na.graph_label, na.style)
            for nb in _:
                dot.node(nb.id, nb.graph_label, nb.style)
                if (nb, na) not in processed:
                    dot.edge(na.id, nb.id)
                    processed.add((na, nb))
        return dot

    def render(self, fpath, view=True):
        self._graphviz().render(fpath, view=view)

    def view(self):
        self._graphviz().view()


class InterferenceGraph(UndirectedGraph):
    """
    Interference graph. Undirected graph containing a node for each
    tensor, and an edge between tensors that are live at the same time.

    This class implements an graph coloring algorithm.

    In a standard graph coloring problem you want to minimize the number of
    buffers allocated.  in this variant of the graph coloring problem we want
    to minimize the total buffer space allocated.  In academic literature this
    variant is refered to as ____.
    """

    def __init__(self, lives):
        """
        Creates the interference graph from the provided liveness information.
        There is an edge in the interference graph whenever two variables are
        live at the same time. Each node is weighted by the memory requirement
        of the underlying tensor.

        This seems to be the performance bottleneck for very large graphs.
        Construction could be optimized, or coloring could be done direclty
        from the liveness information.

        Args:
            lives (op => set(tensor_description)): Live tensors at each point
                                Typically the output of dataflow.liveness()
        """
        neighbors = {x: set() for l in list(lives.values()) for x in l}
        edges = [(u, v) for l in list(lives.values()) for u, v in combinations(l, 2)]
        for u, v in edges:
            neighbors[u].add(v)
            neighbors[v].add(u)
        super(InterferenceGraph, self).__init__(neighbors)
        self.weights = {x: max(1, reduce(mul, x.shape, 1)) *
                        x.dtype.itemsize for x in neighbors}

    def color(self):
        """
        Performs weighted graph coloring on this interference graph.
        Basically implements:
        *Buffer allocation in regular dataflow networks:
        an approach based on coloring circular-arc graphs*, R. Govindarajan

        The PDF link I used seems dead now, and can't find a link without
        an academic account
        """

        neighbors = self.neighbors
        weights = self.weights
        partitions = []
        buffers = []
        queue = sorted(weights, key=lambda x: (weights[x], ), reverse=True)
        while queue:
            u = queue.pop(0)
            # Creates a new set and grows it as much as possible
            S = {u}
            N = neighbors[u]
            for x in queue:
                if x not in N:
                    S |= {x}
                    N |= neighbors[x]
            partitions.append(S)
            color = len(partitions) - 1
            buffers.append(Buffer(color, weights[u]))
            # Update remaining nodes
            queue = [x for x in queue if x not in S]
            for s in S:
                s.buffer = buffers[color]
        total_mem = sum([x.size for x in buffers])
        return total_mem, buffers


def _random_colors(N, alpha=.5):
    from colorsys import hsv_to_rgb
    HSV = [[x * 1.0 / N, 0.5, 0.5] for x in range(N)]
    RGBA = [x + (alpha,) for x in [hsv_to_rgb(*x) for x in HSV]]
    RGBA = [[int(y * 255) for y in x] for x in RGBA]
    HEX = ["#{:02x}{:02x}{:02x}{:02x}".format(
        r, g, b, a) for r, g, b, a in RGBA]
    return HEX


def bind_initializers(transformer, ops):
    for op in ops:
        buffer = op.tensor_description(transformer).buffer
        # assign the same buffer to all of the op's initializers
        for i in op.initializers:
            i.tensor_description(transformer).buffer = buffer
            for a in i.args:
                if isinstance(a, NumPyTensor):
                    a.tensor_description(transformer).buffer = Buffer(-1, a.nptensor.size)
                    a.tensor_description(transformer).buffer.data = a.nptensor


def assign_buffers(transformer, results, fusible=None):
    """
    Performs dataflow analysis ou the graph defined by the provide results.
    Assigns buffer to each node.

    Args:
        results: results to build the graph from

    Returns:
        dfg (DataFlowGraph/KernelFlowGraph): dataflow of the computation
        memory (int): Memory usage of the computations
    """

    dfg = DataFlowGraph(transformer, results)
    all_ops = dfg.successors.keys()
    if fusible:
        dfg = KernelFlowGraph(dfg, fusible)
    ifg = InterferenceGraph(dfg.liveness())
    memory, buffers = ifg.color()
    # Binds initializers
    bind_initializers(transformer, dfg.inputs)
    # set style
    cmap = _random_colors(len(buffers), .5)
    for op in all_ops:
        tensor = op.tensor_description(transformer)
        if tensor.buffer:
            op.style = {'style': 'filled', 'fillcolor': cmap[tensor.buffer.color]}
    # dfg.view()
    return dfg, memory
