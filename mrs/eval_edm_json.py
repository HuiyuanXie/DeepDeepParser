# Copyright 2018 Jan Buys.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""Computes EDM F1 scores."""

import argparse
import json

def list_predicate_spans(triples):
  spans = []
  for triple in triples:
    if len(triple.split(' ')) > 1 and triple.split(' ')[1] == "NAME":
      spans.append(triple.split(' ')[0])  
  return spans

def list_spans(triples):
  spans = set()
  for triple in triples:
    if (len(triple.split(' ')) > 1 and (triple.split(' ')[1] == "NAME" 
        or triple.split(' ')[1] == "CARG")):
      spans.add(triple.split(' ')[0])
    elif len(triple.split(' ')) > 2:
      spans.add(triple.split(' ')[0])
      spans.add(triple.split(' ')[2])
  return list(spans)

def inc_end_spans(spans):
  new_spans = [span.split(':')[0] + ":" + str(int(span.split(':')[1])+1)
               for span in spans]
  return new_spans

def dec_end_spans(spans):
  new_spans = [span.split(':')[0] + ":" + str(int(span.split(':')[1])-1)
               for span in spans]
  return new_spans


class MrsNode():
  def __init__(self, name, concept, start, end):
    self.name = name
    self.concept = concept
    self.start = start
    self.end = end
    self.constant = ""
    self.top = False
    self.edges = []
    self.relations = []

  def span_str(self, include_end=True):
    if include_end:
      return str(self.start) + ":" + str(self.end)
    else:
      return str(self.start) + ":" + str(self.start)

  def append_edge(self, child_index, relation):
    self.edges.append(child_index)
    self.relations.append(relation)


class MrsGraph():
  def __init__(self, nodes, parse_id=-1):
    self.nodes = nodes
    self.parse_id = parse_id

  @classmethod
  def parse_orig_json_line(cls, json_line):
    mrs = json.loads(json_line)
    parse_id = mrs["id"] 
    nodes = []
    nodes_index = {}

    # First parse nodes.
    for node in mrs["nodes"]:
      node_id = node["id"] - 1
      nodes_index[node_id] = len(nodes)
      props = node["properties"] 
      concept = props["predicate"]
      start = node["start"]
      end = node["end"]
      graph_node = MrsNode(str(node_id), concept, start, end)

      if "constant" in props:
        const = props["constant"]
        if const[0] != '"':
          const = '"' + const
        if const[-1] != '"':
          const = const + '"' 
        graph_node.constant = const
      if "top" in node and node["top"]:
        graph_node.top = True

      # ignore features for now
      nodes.append(graph_node)

    # Then add edges.
    for node in mrs["nodes"]:
      parent_ind = nodes_index[node["id"] - 1]
      if "edges" in node:
        for edge in node["edges"]:
          child_ind = nodes_index[edge["target"] - 1]
          label = edge["label"]
          nodes[parent_ind].append_edge(child_ind, label)

    return cls(nodes, parse_id)

  def predicate_bag(self, include_constants=True):
    bag = []
    for i, node in enumerate(self.nodes):
      bag.append(node.concept)
      if include_constants and node.constant:
        bag.append(node.constant)
    return bag

  def predicate_triples(self, include_constants=True, include_span_ends=True):
    triples = []
    for i, node in enumerate(self.nodes):
      triples.append(node.span_str(include_span_ends) + " NAME " + node.concept)
      if include_constants and node.constant:
        triples.append(node.span_str(include_span_ends) + " CARG " + node.constant)

    return triples

  def relation_triples(self, include_span_ends=True, labeled=True):
    triples = []

    for i, node in enumerate(self.nodes): # for order consistency
      if node.top:
        node_ind = node.span_str(include_span_ends)
        triples.append("-1:-1 /H " + node_ind)

    for i, node in enumerate(self.nodes):
      node_ind = node.span_str(include_span_ends)
      for k, child_index in enumerate(node.edges): 
        child_node = self.nodes[child_index]
        child_ind = child_node.span_str(include_span_ends)
        if (node.relations[k] == "/EQ" and (node.start > child_node.start
            or (node.start == child_node.start and node.end > child_node.end))):
          node_ind, child_ind = child_ind, node_ind
        rel = node.relations[k] if labeled else "REL"
        rel = "/EQ/U" if rel == "/EQ" else rel
        triples.append(node_ind + ' ' + rel + ' ' + child_ind)

    return triples

  def eds_triples(self, score_predicates, score_relations,
    include_span_ends=True, include_constants=True, labeled=True,
    include_predicate_spans=True):
    triples = []

    if score_predicates:
      if include_predicate_spans:
        triples.extend(self.predicate_triples(include_constants,
          include_span_ends))
      else:
        triples.extend(self.predicate_bag(include_constants))
    if score_relations:
      triples.extend(self.relation_triples(include_span_ends, labeled))

    return triples


def compute_f1(gold_graphs, predicted_graphs, score_predicates, 
    score_relations, include_constants=True, labeled=True, 
    include_span_ends=True, include_predicate_spans=True, 
    score_nones=True, verbose=False):
  total_gold = 0
  total_predicted = 0
  total_correct = 0
  none_count = 0 
  
  for parse_id, gold_g in gold_graphs.items(): 
    gold_triples = gold_g.eds_triples(score_predicates, score_relations, 
        include_span_ends, include_constants, labeled, include_predicate_spans)
    if parse_id in predicted_graphs:
      predicted_triples = predicted_graphs[parse_id].eds_triples(
        score_predicates, score_relations, include_span_ends, include_constants,
        labeled, include_predicate_spans)
    else:
      predicted_triples = []
      none_count += 1
      if not score_nones:
        gold_triples = [] 

    # Magic to replace end spans off by 1.
    #gold_spans = set(list_predicate_spans(gold_triples))
    #predicted_spans = list_predicate_spans(predicted_triples)
    gold_spans = set(list_spans(gold_triples))
    predicted_spans = list_spans(predicted_triples)

    def replace_new_spans(new_spans):
      for i, new_span in enumerate(new_spans):
        old_span = predicted_spans[i]
        if old_span not in gold_spans and new_span in gold_spans:
          for j, triple in enumerate(predicted_triples):
            predicted_triples[j] = triple.replace(old_span, new_span) # string replacement
            #if old_span in triple and 'NAME' not in triple:
            #  print("%s -> %s" % (triple, predicted_triples[j]))
                  
    replace_new_spans(inc_end_spans(predicted_spans))
    replace_new_spans(dec_end_spans(predicted_spans))

    #if not score_predicates and not include_span_ends:
    #  for tri in gold_triples:
    #    print(tri)

    gold_triples = set(gold_triples)
    predicted_triples = set(predicted_triples)

    correct_triples = gold_triples.intersection(predicted_triples)
    incorrect_predicted = predicted_triples - correct_triples
    missed_predicted = gold_triples - correct_triples

    if verbose and not include_predicate_spans:
      if incorrect_predicted:
        print("Incorrect: %s" % incorrect_predicted)
      if missed_predicted:
        print("Missed: %s" % missed_predicted)

    total_gold += len(gold_triples)
    total_predicted += len(predicted_triples)
    total_correct += len(correct_triples)

  assert total_predicted > 0 and total_gold > 0, "No correct predictions"

  #print(total_correct)
  #print(total_predicted)
  #print(total_gold)
  precision = total_correct/total_predicted
  recall = total_correct/total_gold
  f1 = 2*precision*recall/(precision+recall)

  if verbose:
    print("Precision: {:.2%}".format(precision))
    print("Recall: {:.2%}".format(recall))
  print("F1-score: {:.2%}".format(f1))
 

if __name__=='__main__': 
  parser = argparse.ArgumentParser()
  parser.add_argument("-g", "--gold", help="gold dmrs.orig.json file",
          required=True)
  parser.add_argument("-s", "--system", help="system dmrs json file",
          required=True)
  parser.add_argument("-t", "--toks", help="tokenization and preprocessing .tok.json file")
  parser.add_argument("-x", "--text", help="tokenization and preprocessing .tok.json file")
  parser.add_argument("--orig", help="score orig system file",
          action="store_true")

  parser.add_argument("--exclude_constants", help="do not score constant arguments",
          action="store_true")
  parser.add_argument("--unlabeled", help="do not score constant arguments",
          action="store_true")
  parser.add_argument("--exclude_missing_graphs", help="do not score constant arguments",
          action="store_true")

  parser.add_argument("--detailed", help="Detailed F1 scores",
          action="store_true")
  parser.add_argument("--verbose", action="store_true")
  args = parser.parse_args()

  assert args.orig #TODO implement conversion
  if not args.orig:
    assert args.tokens and arg.text

  include_constants = not args.exclude_constants
  labeled = not args.unlabeled
  score_nones = not args.exclude_missing_graphs

  with open(args.gold, 'r') as fg:
    gold_graphs = {}
    for line in fg:
      graph = MrsGraph.parse_orig_json_line(line.strip()) 
      gold_graphs[graph.parse_id] = graph

  with open(args.system, 'r') as fs:
    predicted_graphs = {}
    for line in fs:
      graph = MrsGraph.parse_orig_json_line(line.strip()) 
      predicted_graphs[graph.parse_id] = graph

  print("Full EDM")
  compute_f1(gold_graphs, predicted_graphs, True, True,
        include_constants, labeled,
        score_nones=score_nones, verbose=args.verbose)

  print("Predicate EDM")
  compute_f1(gold_graphs, predicted_graphs, True, False,
        include_constants, 
        score_nones=score_nones, verbose=args.verbose)

  print("Relation EDM")
  compute_f1(gold_graphs, predicted_graphs, False, True,
          include_constants, labeled, 
          score_nones=score_nones, verbose=args.verbose)

  if args.detailed:
    print("Full EDM, start spans only")
    compute_f1(gold_graphs, predicted_graphs, True, True,
            include_constants, labeled, include_span_ends=False,
            score_nones=score_nones, verbose=args.verbose)

    print("Predicate EDM, start spans only")
    compute_f1(gold_graphs, predicted_graphs, True, False,
            include_constants, include_span_ends=False,
            score_nones=score_nones, verbose=args.verbose)

    print("Predicate EDM, ignoring spans")
    compute_f1(gold_graphs, predicted_graphs, True, False,
            include_constants, include_predicate_spans=False,
            score_nones=score_nones, verbose=args.verbose)

  print("Relation EDM, start spans only")
  compute_f1(gold_graphs, predicted_graphs, False, True,
            include_constants, labeled, include_span_ends=False,
            score_nones=score_nones, verbose=args.verbose)
