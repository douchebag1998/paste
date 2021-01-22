import numpy as np
import pandas as pd
import ot
from sklearn.decomposition import NMF
from numpy import linalg as LA
from .STLayer import STLayer
from scipy.spatial import distance_matrix
from .helper import generateDistanceMatrix, kl_divergence, intersect

def pairwise_align(layer1, layer2, alpha = 0.1):
    """
    Calculates and returns optimal alignment of two layers. 
    
    param: layer1 - STLayer object of first layer
    param: layer2 - STLayer object of second layer
    param: alpha - Alignment tuning parameter. Note: 0 ≤ alpha ≤ 1
    
    return: pi - alignment of spots
    """
    
    # subset for common genes
    common_genes = intersect(layer1.gene_exp.columns.tolist(), layer2.gene_exp.columns.tolist())
    layer1.subset_genes(common_genes)
    layer2.subset_genes(common_genes)
    
    D1 = generateDistanceMatrix(layer1, layer1)
    D2 = generateDistanceMatrix(layer2, layer2)
    l1 = layer1.gene_exp.to_numpy() + 0.01
    l2 = layer2.gene_exp.to_numpy() + 0.01
    M = kl_divergence(l1, l2)
    a = np.ones((layer1.gene_exp.shape[0],))/layer1.gene_exp.shape[0]
    b = np.ones((layer2.gene_exp.shape[0],))/layer2.gene_exp.shape[0]
    pi, logw = ot.gromov.fused_gromov_wasserstein(M, D1.to_numpy(), D2.to_numpy(), a, b, loss_fun='square_loss', alpha= alpha, verbose=False, log=True)
    return pi

def center_align(A, layers, lmbda, alpha = 0.1, n_components = 15, threshold = 0.001):
    """
    Computes center alignment of layers.
    
    param: A - Initialization of starting STLayer; include gene expression AND spatial
    param: layers - List of STLayers used to calculate center alignment
    param: lmbda - List of probability weights assigned to each STLayer
    param: n_components - Number of components in NMF decomposition
    param: threshold - Threshold for convergence of W and H
    
    return: W, H - low dimensional representation of gene expression matrix of center layer
    return: pi - List of pairwise alignment mappings of each layer to the center layer
    """
    A = A.copy()
    
    # get common genes
    common_genes = A.gene_exp.columns.to_list()
    for l in layers:
        common_genes = intersect(common_genes, l.gene_exp.columns.to_list())
    
    # subset common genes
    A.subset_genes(common_genes)
    for l in layers:
        l.subset_genes(common_genes)

    # calculate local euclidean distance matrix
    D = []
    for layer in layers:
        D.append(generateDistanceMatrix(layer, layer))
    model = NMF(n_components=n_components, init='random', random_state=0)
    W = model.fit_transform(A.gene_exp)
    H = model.components_
    center_coordinates = A.coordinates
    # Initialize D_center
    center_layer = STLayer(np.dot(W, H), center_coordinates)
    center_layer.gene_exp.columns = common_genes
    D_center = generateDistanceMatrix(center_layer, center_layer)
    iteration_count = 0
    R = 0
    R_diff = 100
    while R_diff > 0.001 and iteration_count < 10:
        print("Iteration: " + str(iteration_count))
        pi, M = center_ot(W, H, layers, center_coordinates, common_genes, alpha)
        W, H = center_NMF(W, H, layers, pi, lmbda, n_components)

        R_new = objective_function(layers, pi, M, D, D_center, lmbda, alpha)
        iteration_count += 1
        R_diff = abs(R - R_new)
        print("R - R_new: " + str(R_diff))
        R = R_new
    return W, H, pi

#--------------------------- HELPER METHODS -----------------------------------

def center_ot(W, H, layers, center_coordinates, common_genes, alpha):
    center_layer = STLayer(np.dot(W, H), center_coordinates)
    center_layer.gene_exp.columns = common_genes

    pi = []
    M = []
    for l in layers:
        p, m = pairwise_align2(center_layer, l, alpha = alpha)
        pi.append(p)
        M.append(m)
    return pi, M

def center_NMF(W, H, layers, pi, lmbda, n_components):
    n = W.shape[0]
    B = n*sum([lmbda[i]*np.dot(pi[i], layers[i].gene_exp) for i in range(len(layers))])
    model = NMF(n_components=n_components, init='random', random_state=0)
    W_new = model.fit_transform(B)
    H_new = model.components_
    return W_new, H_new


def objective_function(layers, pi, M, D, D_center, lmbda, alpha):
    """
    Calculates objective function R we are trying to minimize.
    
    param: layers - List of STLayers used to calculate center alignment
    param: pi - List of ot maps between (center layer, layer_q)
    param: M - List of cost matrices between (center layer, layer_q)
    param: D - List of local distance matrices for each layer_q
    param: D_center - local distance matrix of center_layer
    param: lmbda - List of probability weights assigned to each Layer
    param: alpha - determines weight assigned to each term in function
    
    return: R - objective value
    """
    R = 0
    for q in range(len(layers)):
        first_term = np.sum(np.multiply(pi[q], M[q]))
        # calculate second term
        t = np.nonzero(pi[q])
        second_term = 0
        for c1 in range(len(t[0])):
            for c2 in range(len(t[0])):
                i = t[0][c1]
                j = t[1][c1]
                k = t[0][c2]
                l = t[1][c2]
                second_term += ((D_center.iloc[i, k] - D[q].iloc[j, l])**2)*pi[q][i,j]*pi[q][k,l]
        R += lmbda[q]*((1-alpha)*first_term + alpha*second_term)
    return R


def pairwise_align2(layer1, layer2, alpha = 0.1):
    """
    Calculates and returns optimal alignment of two layers. Assumes count matrix is preprocessed.
    EXACT SAME as pairwise_align, but also returns M.
    
    param: layer1 - STLayer object of first layer
    param: layer2 - STLayer object of second layer
    param: alpha - Alignment tuning parameter. Note: 0 ≤ alpha ≤ 1
    
    return: pi - alignment of spots
    return: M - kl_divergence similarity matrix
    """
    layer1 = layer1.copy()
    layer2 = layer2.copy()
    D1 = generateDistanceMatrix(layer1, layer1)
    D2 = generateDistanceMatrix(layer2, layer2)
    l1 = layer1.gene_exp.to_numpy() + 0.01
    l2 = layer2.gene_exp.to_numpy() + 0.01
    M = kl_divergence(l1, l2)
    a = np.ones((layer1.gene_exp.shape[0],))/layer1.gene_exp.shape[0]
    b = np.ones((layer2.gene_exp.shape[0],))/layer2.gene_exp.shape[0]
    pi, logw = ot.gromov.fused_gromov_wasserstein(M, D1.to_numpy(), D2.to_numpy(), a, b, loss_fun='square_loss', alpha= alpha, verbose=False, log=True)
    return pi, M



