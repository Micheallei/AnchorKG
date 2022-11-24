import torch
import torch.nn as nn
from utils import *
import numpy as np
import networkx as nx
from model.base_model import BaseModel

class Reasoner(BaseModel):

    def __init__(self, config, entity_embedding, relation_embedding, device=torch.device('cpu')):
        super(Reasoner, self).__init__()
        self.device = device
        self.config = config
        self.tanh = nn.Tanh()
        self.gru = torch.nn.GRU(self.config['embedding_size'], self.config['embedding_size']).to(device)
        self.sigmoid = nn.Sigmoid()
        self.elu = nn.ELU()
        self.gru_layer = nn.Sequential(
            nn.Linear(self.config['embedding_size'], self.config['embedding_size']),
            nn.ELU(),
            nn.Linear(self.config['embedding_size'],1),
        ).to(device)
        self.entity_embedding = nn.Embedding.from_pretrained(entity_embedding)
        self.relation_embedding = nn.Embedding.from_pretrained(relation_embedding)
        self.entity_compress =  nn.Sequential(
                                    nn.Linear(self.config['entity_embedding_size'], self.config['embedding_size']),
                                    nn.Tanh(),
                                ).to(device)
        self.relation_compress = nn.Sequential(
                                    nn.Linear(self.config['entity_embedding_size'], self.config['embedding_size']),
                                    nn.Tanh(),
                                ).to(device)

    def get_overlap_entities(self, anchor_graph1, anchor_graph2):
        overlap_entity_num = []
        anchor_graph1_num = []
        anchor_graph2_num = []
        for i in range(len(anchor_graph1)):
            anchor_graph1_set = set()
            anchor_graph2_set = set()
            for anchor_node in anchor_graph1[i]:
                anchor_graph1_set.add(int(anchor_node))
            for anchor_node in anchor_graph2[i]:
                anchor_graph2_set.add(int(anchor_node))
            anchor_graph1_set.discard(0)
            anchor_graph2_set.discard(0)
            overlap_entity_num.append(len(anchor_graph1_set & anchor_graph2_set))
            anchor_graph1_num.append(len(anchor_graph1_set))
            anchor_graph2_num.append(len(anchor_graph2_set))
        overlap_entity_num_cpu = overlap_entity_num
        return torch.tensor(overlap_entity_num).to(self.device), torch.tensor(anchor_graph1_num).to(self.device), torch.tensor(anchor_graph2_num).to(self.device), overlap_entity_num_cpu

    def get_anchor_graph_list(self, anchor_graph_layers, batch_size):
        anchor_graph_list_flat = []#flattened，(batch,50)
        anchor_graph_list = []#hierarchical，(batch,[5,15,30])
        for i in range(batch_size):
            anchor_graph_list_flat.append([])
            anchor_graph_list.append([[],[],[]])
        for i in range(len(anchor_graph_layers)):
            for j in range(len(anchor_graph_layers[i])):
                for k in range(len(anchor_graph_layers[i][j])):
                    anchor_graph_list[j][i].append(int(anchor_graph_layers[i][j][k].data.cpu().numpy()))
                    anchor_graph_list_flat[j].append(int(anchor_graph_layers[i][j][k].data.cpu().numpy()))
        return anchor_graph_list_flat, anchor_graph_list

    def get_path_score(self, reasoning_paths):
        predict_scores = []
        for paths in reasoning_paths:
            predict_scores.append([0])
            for path in paths:
                path_node_embeddings = self.entity_compress(self.entity_embedding(torch.tensor(path)).to(self.device))
                if len(path_node_embeddings.shape) == 1:
                    path_node_embeddings = torch.unsqueeze(path_node_embeddings, 0)
                path_node_embeddings = torch.unsqueeze(path_node_embeddings, 1)
                output, h_n = self.gru(path_node_embeddings)
                path_score = (self.gru_layer(torch.squeeze(output[-1])))
                predict_scores[-1].append(path_score)
            predict_scores[-1] = torch.sum(predict_scores[-1]).float()
        return torch.stack(predict_scores).to(self.device)

    def get_reasoning_paths(self, news1, news2, anchor_graph1, anchor_graph2, anchor_relation1, anchor_relation2, overlap_entity_num_cpu):
        reasoning_paths = []
        reasoning_edges = []
        for i in range(len(news1)):
            if overlap_entity_num_cpu[i]>0:
                subgraph = nx.MultiGraph()
                for index1 in range(self.config['topk'][0]):
                    if anchor_graph1[i][0][index1] != 0:
                        subgraph.add_edge(news1[i], anchor_graph1[i][0][index1], weight=0)
                    if anchor_graph2[i][0][index1] != 0:
                        subgraph.add_edge(news2[i], anchor_graph2[i][0][index1], weight=0)
                    for index2 in range(self.config['topk'][1]):
                        if anchor_graph1[i][1][index1*self.config['topk'][1]+index2] != 0:
                            subgraph.add_edge(anchor_graph1[i][0][index1], anchor_graph1[i][1][index1*self.config['topk'][1]+index2], weight=anchor_relation1[1][i][index1*self.config['topk'][1]+index2])
                        if anchor_graph2[i][1][index1*self.config['topk'][1]+index2] != 0:
                            subgraph.add_edge(anchor_graph2[i][0][index1], anchor_graph2[i][1][index1*self.config['topk'][1]+index2], weight=anchor_relation2[1][i][index1*self.config['topk'][1]+index2])
                        for index3 in range(self.config['topk'][2]):
                            if anchor_graph1[i][2][index1*self.config['topk'][1]*self.config['topk'][2]+index2*self.config['topk'][2]+index3] != 0:
                                subgraph.add_edge(anchor_graph1[i][1][index1*self.config['topk'][1]+index2], anchor_graph1[i][2][index1*self.config['topk'][1]*self.config['topk'][2]+index2*self.config['topk'][2]+index3], weight=anchor_relation1[2][i][index1*self.config['topk'][1]*self.config['topk'][2]+index2*self.config['topk'][2]+index3])
                            if anchor_graph2[i][2][index1*self.config['topk'][1]*self.config['topk'][2]+index2*self.config['topk'][2]+index3] != 0:
                                subgraph.add_edge(anchor_graph2[i][1][index1*self.config['topk'][1]+index2], anchor_graph2[i][2][index1*self.config['topk'][1]*self.config['topk'][2]+index2*self.config['topk'][2]+index3], weight=anchor_relation2[2][i][index1*self.config['topk'][1]*self.config['topk'][2]+index2*self.config['topk'][2]+index3])
                reasoning_paths.append([])
                reasoning_edges.append([])
                for path in nx.all_simple_paths(subgraph, source=news1[i], target=news2[i], cutoff=5):
                    reasoning_paths[-1].append(path[1:-1])
                    reasoning_edges[-1].append([])
                    for i in range(len(path)-2):
                        reasoning_edges[-1][-1].append(int(subgraph[path[i]][path[i+1]][0]['weight']))
            else:
                reasoning_paths.append([0])
                reasoning_edges.append([0])
        return reasoning_paths, reasoning_edges

    def forward(self, news1, news2, anchor_graph1, anchor_graph2, anchor_relation1, anchor_relation2):

        anchor_graph_list1_flat, anchor_graph_list1 = self.get_anchor_graph_list(anchor_graph1, len(news1))
        anchor_graph_list2_flat, anchor_graph_list2 = self.get_anchor_graph_list(anchor_graph2, len(news2))
        overlap_entity_num, anchor_graph1_num, anchor_graph2_num, overlap_entity_num_cpu = self.get_overlap_entities(anchor_graph_list1_flat, anchor_graph_list2_flat)
        reasoning_paths, reasoning_edges = self.get_reasoning_paths(news1, news2, anchor_graph_list1, anchor_graph_list2, anchor_relation1, anchor_relation2, overlap_entity_num_cpu)
        predict_scores = []
        paths_scores = []
        for i in range(len(reasoning_paths)):
            paths = reasoning_paths[i]
            edges = reasoning_edges[i]
            predict_scores.append(torch.zeros([1]).to(self.device))
            paths_scores.append([])
            for j in range(len(paths)):
                path_node_embeddings = self.entity_compress(self.entity_embedding(torch.tensor(paths[j])).to(self.device))
                path_edge_embeddings = self.relation_compress(self.relation_embedding(torch.tensor(edges[j])).to(self.device))
                if len(path_node_embeddings.shape) == 1:
                    path_node_embeddings = torch.unsqueeze(path_node_embeddings, 0)
                    path_edge_embeddings = torch.unsqueeze(path_edge_embeddings, 0)
                path_node_embeddings = torch.unsqueeze(path_node_embeddings, 1)
                path_edge_embeddings = torch.unsqueeze(path_edge_embeddings, 1)
                output, h_n = self.gru(path_node_embeddings+path_edge_embeddings)
                path_score = self.sigmoid(self.gru_layer(torch.squeeze(output[-1])))
                predict_scores[-1] = predict_scores[-1] + path_score
                paths_scores[-1].append(path_score)
        paths_predict_score = torch.cat(predict_scores, dim=0)
        predicts_qua = self.tanh(torch.div(paths_predict_score, (torch.log((torch.e+anchor_graph1_num+anchor_graph2_num).to(torch.float32)))))
        predicts_num = self.tanh(torch.div(overlap_entity_num, (torch.log((torch.e+anchor_graph1_num+anchor_graph2_num).to(torch.float32)))))
        predicts = 0.8*predicts_qua + 0.2*predicts_num
        return predicts, reasoning_paths,reasoning_edges, paths_scores
