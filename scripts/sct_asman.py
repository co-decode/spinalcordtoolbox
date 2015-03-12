#!/usr/bin/env python
########################################################################################################################
#
# Asman et al. groupwise multi-atlas segmentation method implementation
# The name of the attributes of each class correspond to the names in Asman et al. paper
#
# ----------------------------------------------------------------------------------------------------------------------
# Copyright (c) 2014 Polytechnique Montreal <www.neuro.polymtl.ca>
# Authors: Augustin Roux, Sara Dupont
# Modified: 2015-03-12
#
# About the license: see the file LICENSE.TXT
########################################################################################################################

# TODO change 'target' by 'input'
#TODO : make it faster !! (maybe the imports are very slow ...)

#TODO: is scipy.misc.toimage really needed ?
#from scipy.misc import toimage
from msct_pca import PCA
import numpy as np
from scipy.optimize import minimize
from math import sqrt
from math import exp
from math import log
from math import pi
from math import fabs
from msct_image import Image
from msct_parser import *
import matplotlib.pyplot as plt
import sct_utils as sct
import os



class Param:
    def __init__(self):
        self.debug = 0
        self.path_dictionary = '/Volumes/folder_shared/greymattersegmentation/data_asman/dictionary'
        #self.patient_id = ['09', '24', '30', '31', '32', '25', '10', '08', '11', '16', '17', '18']
        self.include_GM = 0
        self.split_data = 1  # this flag enables to duplicate the image in the right-left direction in order to have more dataset for the PCA
        self.verbose = 0

########################################################################################################################
######------------------------------------------------- Classes --------------------------------------------------######
########################################################################################################################

# ----------------------------------------------------------------------------------------------------------------------
# DATA -----------------------------------------------------------------------------------------------------------------
class Data:
    def __init__(self, param=None):
        if param is None:
            self.param = Param()
        else:
            self.param = param

        # Load all the images' slices from param.path_dictionary
        sct.printv('\nLoading dictionary ...', self.param.verbose, 'normal')
        #List of atlases (A) and their label decision (D) (=segmentation of the gray matter), slice by slice
        #zip(self.A,self.D) would give a list of tuples (slice_image,slice_segmentation)
        self.A, self.D = self.load_dictionary()

        #number of atlases in the dataset
        self.J = len(self.A)
        #dimension of the data (flatten slices)
        self.N = len(self.A[0].flatten())

        #set of possible labels that can be assigned to a given voxel in the segmentation
        self.L = [0, 1] #1=GM, 0=WM or CSF

        sct.printv('\nComputing the rigid transformation to coregister all the data into a common groupwise space ...', self.param.verbose, 'normal')
        #list of rigid transformation for each slice to coregister the data into the common groupwise space
        self.RM = self.rigid_coregistration()

        sct.printv('\nCoregistering all the data into the common groupwise space ...', self.param.verbose, 'normal')
        #List of atlases (A_M) and their label decision (D_M) (=segmentation of the gray matter), slice by slice in the common groupwise space
        #zip(self.A_M,self.D_M) would give a list of tuples (slice_image,slice_segmentation)
        self.A_M, self.D_M = self.coregister_dataset()

        #self.show_data()

    # ------------------------------------------------------------------------------------------------------------------
    # Load the dictionary:
    # each slice of each patient will be load separately in A with its corresponding GM segmentation in D
    def load_dictionary(self):
        # init
        atlas_slices = []
        decision_slices = []
        # loop across all the volume
        #TODO: change the name of files to find to a more general structure
        for subject_dir in os.listdir(self.param.path_dictionary):
            subject_path = self.param.path_dictionary + '/' + subject_dir
            if os.path.isdir(subject_path):
                subject_seg_in = ''
                subject_GMr = ''
                for file in os.listdir(subject_path):
                    if 'seg_in.nii' in file:
                        subject_seg_in = file
                    if self.param.include_GM and 'GM.nii' in file:
                        subject_GM = file

                atlas = Image(subject_path + '/' + subject_seg_in)
                if self.param.include_GM:
                    seg = Image(subject_path + '/' + subject_GM)

                index_s = 0
                for slice in atlas.data:
                    if self.param.split_data:
                        left_slice, right_slice = split(slice)
                        atlas_slices.append(left_slice)
                        atlas_slices.append(right_slice)
                        if self.param.include_GM:
                            seg_slice = seg.data[index_s]
                            left_slice_seg, right_slice_seg = split(seg_slice)
                            decision_slices.append(left_slice_seg)
                            decision_slices.append(right_slice_seg)
                        else:
                            decision_slices.append(None)
                            decision_slices.append(None)

                    else:
                        atlas_slices.append(slice)
                        if self.param.include_GM:
                            seg_slice = seg.data[index_s]
                            decision_slices.append(seg_slice)
                        else:
                            decision_slices.append(None)
                    index_s += 1

        return atlas_slices, decision_slices

    # ------------------------------------------------------------------------------------------------------------------
    # return the rigid transformation (for each slice, computed on D data) to coregister all the atlas information to a common groupwise space
    def rigid_coregistration(self):
        convergence = False
        ##initialization
        R = []
        Dm = []
        #chi = max(sum([[self.kronecker_delta(i,l) for i in slice[1].data] for slice in self.list_atlas_seg]) for l in self.L)
        chi = self.compute_chi(self.D)

        for j,Dj in enumerate(self.D):
            R.append(self.find_R(chi, Dj))
            Dm.append(apply_2D_rigid_transformation(Dj, R[j]['tx'], R[j]['ty'], R[j]['theta']))

        k = 1
        while not convergence:
            chi_old = chi
            chi = self.compute_chi(Dm)
            k += 1
            if chi_old == chi:
                convergence = True
            elif k > 15:
                sct.printv('WARNING: did not achieve convergence for the coregistration to a common groupwise space...', 1, 'warning')
                break
            else:
                for j,Dmj in enumerate(Dm):
                    R[j] = self.find_R(chi, Dmj)
                    Dm[j] = apply_2D_rigid_transformation(Dmj, R[j]['tx'], R[j]['ty'], R[j]['theta'])

        #TODO: save chi image to visualize the mean segmentation image
        #save_square_image(chi, 'mean_seg')
        return R

    # ------------------------------------------------------------------------------------------------------------------
    # Compute the mean segmentation image 'chi' for a given decision dataset D
    def compute_chi(self, D):
        chi = []
        choose_maj_vote = {}
        for l in self.L:
            to_be_summed = []
            for slice in D:
                consistent_vox = []
                for row in slice:
                    for i in row:
                        if i > 0.2:
                            i = 1
                        consistent_vox.append(kronecker_delta(i, l))
                to_be_summed.append(consistent_vox)
            summed_vector = np.zeros(len(to_be_summed[0]), dtype=np.int)
            for v in to_be_summed:
                summed_vector = np.add(summed_vector, v)
            choose_maj_vote[l] = summed_vector

        for vote_tuple in zip(choose_maj_vote[0], choose_maj_vote[1]):
            if vote_tuple[0] >= vote_tuple[1]:
                chi.append(0)
            elif vote_tuple[1] > vote_tuple[0]:
                chi.append(1)
        return chi

    # ------------------------------------------------------------------------------------------------------------------
    # label-based cost function that RM must minimize
    def R_l0_norm(self, params, (chi, D)):
        tx, ty, theta = params
        return np.linalg.norm(chi - apply_2D_rigid_transformation(D, tx, ty, theta).flatten(), 0)

    # ------------------------------------------------------------------------------------------------------------------
    # minimization of the label-based cost function to find the rigid registration we want
    def find_R(self, chi, D):
        xlim, ylim = D.shape
        start_params = [0,0,0] #[tx, ty, theta]
        fixed_params = (chi, D)

        #params_bounds = ((0,xlim), (0,ylim), (0,2*pi))
        #res = minimize(self.R_l0_norm, start_params, args=(fixed_params,), bounds = params_bounds, method='SLSQP', options={'disp': False ,'eps' : 1.0})
        res = minimize(self.R_l0_norm, start_params, args=(fixed_params,), method='Nelder-Mead')


        #print '\n', res


        R = {'tx': res.x[0], 'ty' : res.x[1], 'theta' : res.x[2]}
        return R

    # ------------------------------------------------------------------------------------------------------------------
    # return the coregistered data into the common groupwise space using the previously computed rigid transformation :self.RM
    def coregister_dataset(self):
        A_M = []
        D_M = []
        for j in range(self.J):
            atlas_M = apply_2D_rigid_transformation(self.A[j], self.RM[j]['tx'], self.RM[j]['ty'], self.RM[j]['theta'])
            A_M.append(atlas_M)
            decision_M = apply_2D_rigid_transformation(self.D[j], self.RM[j]['tx'], self.RM[j]['ty'], self.RM[j]['theta'])
            D_M.append(decision_M)

        return A_M, D_M

    def show_data(self):
        for j in range(self.J):
            fig = plt.figure()

            d = fig.add_subplot(1,2, 1)
            d.set_title('Original segmentation')
            im_D = d.imshow(self.D[j])
            im_D.set_interpolation('nearest')
            im_D.set_cmap('gray')

            dm = fig.add_subplot(1,2, 2)
            dm.set_title('Segmentation in the common groupwise space')
            im_DM = dm.imshow(self.D_M[j])
            im_DM.set_interpolation('nearest')
            im_DM.set_cmap('gray')

            plt.suptitle('Slice ' + str(j) + '\n' + str(self.RM[j]))
            plt.show()


# ----------------------------------------------------------------------------------------------------------------------
# APPEARANCE MODEL -----------------------------------------------------------------------------------------------------
class AppearanceModel:
    def __init__(self, param=None):
        if param is None:
            self.param = Param()
        else:
            self.param = param

        self.data = Data(param=param)

        # Construct a dataset composed of all the slices of flatten images registered into the common groupwise space
        dataset = self.construct_flatten_dataset()
        sct.printv("The shape of the dataset used for the PCA is {}".format(dataset.shape), verbose=self.param.verbose)
        # Instantiate a PCA object given the dataset just build
        sct.printv('\nCreating a reduced common space (using a PCA) ...', self.param.verbose, 'normal')
        self.pca = PCA(dataset, k=0.8) #WARNING : k usually is 0.8

    # ------------------------------------------------------------------------------------------------------------------
    # in order to build the PCA from all the J atlases, we must construct a matrix of J columns and N rows,
    # with N the dimension of flattened images
    def construct_flatten_dataset(self):
        dataset = []
        for atlas_slice in self.data.A_M:
            dataset.append(atlas_slice.flatten())
        return np.asarray(dataset).T


# ----------------------------------------------------------------------------------------------------------------------
# RIGID REGISTRATION ---------------------------------------------------------------------------------------------------
class RigidRegistration:
    def __init__(self, appearance_model, target_image=None):
        self.appearance_model = appearance_model
        # Get the target image
        self.target = target_image
        # coord_projected_target is a list of all the coord of the target's projected slices
        sct.printv('\nProjecting the target image in the reduced common space ...', appearance_model.param.verbose, 'normal')
        self.coord_projected_target = appearance_model.pca.project(target_image) if target_image is not None else None
        self.beta = self.compute_beta()
        self.mu = []
        for beta_slice in self.beta:
            self.mu.append(appearance_model.pca.omega.dot(beta_slice))
        self.sigma = self.compute_sigma()

    # ------------------------------------------------------------------------------------------------------------------
    # beta is the model similarity between all the individual images and our input image
    # beta = (1/Z)exp(-tau*square_norm(omega-omega_j))
    # Z is the partition function that enforces the constraint tha sum(beta)=1
    def compute_beta(self):
        beta = []
        ####decay_constants = self.compute_geodesic_distances()[1]
        tau = 0.005 #1 #decay constant associated with the geodesic distance between a given atlas and the projected target image in model space.
        if self.coord_projected_target is not None:
            for i,coord_projected_slice in enumerate(self.coord_projected_target):
                beta_slice = []
                # in omega matrix, each column correspond to the projection of one of the original data image,
                # the transpose operator .T enable the loop to iterate over all the images coord
                for omega_j in self.appearance_model.pca.omega.T:
                    square_norm = np.linalg.norm((omega_j - coord_projected_slice), 2)
                    beta_slice.append(exp(-tau*square_norm))

                Z = sum(beta_slice)
                for i, b in enumerate(beta_slice):
                    beta_slice[i] = (1/Z) * b

                beta.append(beta_slice)
            return beta
        else:
            raise Exception("No projected input in the appearance model")

    def compute_sigma(self):
        sigma = []
        j = 0
        for beta_slice in self.beta:
            for w_v in self.appearance_model.pca.omega.T:
                sigma_slice = []
                sig = 0
                for w_j in w_v:
                    sig += beta_slice[j]*(w_j - self.mu[j])
                sigma_slice.append(sig)
                sigma.append(sigma_slice)
        return sigma

    # ------------------------------------------------------------------------------------------------------------------
    # plot the pca and the target projection if target is provided
    def plot_omega(self):
        self.appearance_model.pca.plot_omega(target_coord=self.coord_projected_target) if self.coord_projected_target is not None \
            else self.appearance_model.pca.plot_omega()

    # ------------------------------------------------------------------------------------------------------------------
    def show_projected_target(self):
        # Retrieving projected image from the mean image & its coordinates
        import copy

        index = 0
        fig1 = plt.figure()
        fig2 = plt.figure()
        # loop across all the projected slices coord
        for coord in self.coord_projected_target:
            img_reducted = copy.copy(self.appearance_model.pca.mean_image)
            # loop across coord and build projected image
            for i in range(0, coord.shape[0]):
                img_reducted += int(coord[i][0]) * self.appearance_model.pca.W.T[i].reshape(self.appearance_model.pca.N, 1)

            if self.appearance_model.param.split_data:
                n = int(sqrt(self.appearance_model.pca.N * 2))
            else:
                n = int(sqrt(self.appearance_model.pca.N))

            # plot mean image
            # if self.param.split_data:
            #     imgplot = plt.imshow(self.pca.mean_image.reshape(n / 2, n))
            # else:
            #     imgplot = plt.imshow(self.pca.mean_image.reshape(n, n))
            # imgplot.set_interpolation('nearest')
            # imgplot.set_cmap('gray')
            # plt.title('Mean Image')
            # plt.show()
            #
            # Plot original image
            orig_ax = fig1.add_subplot(10, 3, index)
            orig_ax.set_title('original slice {} '.format(index))
            if self.appearance_model.param.split_data:
                imgplot = orig_ax.imshow(self.target.data[index, :, :].reshape(n / 2, n))
            else:
                imgplot = orig_ax.imshow(self.target.data[index].reshape(n, n))
            imgplot.set_interpolation('nearest')
            imgplot.set_cmap('gray')
            # plt.title('Original Image')
            # plt.show()

            index += 1
            # Plot projected image image
            proj_ax = fig2.add_subplot(10, 3, index)
            proj_ax.set_title('slice {} projected'.format(index))
            if self.appearance_model.param.split_data:
                imgplot = proj_ax.imshow(img_reducted.reshape(n / 2, n))
                #imgplot = plt.imshow(img_reducted.reshape(n / 2, n))
            else:
                # imgplot = plt.imshow(img_reducted.reshape(n, n))
                imgplot = proj_ax.imshow(img_reducted.reshape(n, n))
            imgplot.set_interpolation('nearest')
            imgplot.set_cmap('gray')
            # plt.title('Projected Image')
            # plt.show()
        plt.show()



    """
    #TODO:
    #TODO : find how to compute teh decay constant associated with the geodesic distance between a given atlas and the projected target image in model space...
    #---> cannot be computed that way because the decay doesnt fit an exponential ...
    # ------------------------------------------------------------------------------------------------------------------
    # Must return all the geodesic distances between self.appearance_model.pca.omega and the projected target image
    def compute_geodesic_distances(self):
        target_geodesic_dist = []
        decay_constants = []
        for nSlice in range(self.coord_projected_target.shape[0]):
            slice_geodesic_dist = []
            for coord_projected_atlas in self.appearance_model.pca.omega.T:
                slice_geodesic_dist.append(self.geodesic_dist(self.coord_projected_target[nSlice,], coord_projected_atlas))

            target_geodesic_dist.append(slice_geodesic_dist)

            decay = sorted(slice_geodesic_dist)
            decay.reverse()
            slice_tau = log(decay[1]/decay[0])

            decay_constants.append(slice_tau)

        return target_geodesic_dist, decay_constants


    # ------------------------------------------------------------------------------------------------------------------
    # Must return the geodesic distance between two arrays
    def geodesic_dist(self, array1, array2):
        assert (array1.shape == (self.appearance_model.pca.kept,1) or array1.shape == (self.appearance_model.pca.kept,)) and (array2.shape == (self.appearance_model.pca.kept,1) or array2.shape == (self.appearance_model.pca.kept,))

        gdist = 0
        for i in range(self.appearance_model.pca.kept):
            #weighted euclidean norm using the eigenvalues as weights
            gdist += sqrt((array1[i].astype(np.float) - array2[i].astype(np.float))**2) * self.appearance_model.pca.eig_pairs[i][0]
        return gdist

        ##self.appearance_model.pca.omega.T[0] #--> size 6 = first row for all the eigenvalues
        ##self.appearance_model.pca.omega[0] #--> size J = column of values for the first eigenvalue
    """








########################################################################################################################
######------------------------------------------------ FUNCTIONS -------------------------------------------------######
########################################################################################################################


# ----------------------------------------------------------------------------------------------------------------------
# Split a slice in two slices, used to deal with actual loss of data
def split(slice):
    left_slice = []
    right_slice = []
    column_length = slice.shape[1]
    i = 0
    for column in slice:
        if i < column_length / 2:
            left_slice.append(column)
        else:
            right_slice.insert(0, column)
        i += 1
    left_slice = np.asarray(left_slice)
    right_slice = np.asarray(right_slice)
    assert (left_slice.shape == right_slice.shape), \
        str(left_slice.shape) + '==' + str(right_slice.shape) + \
        'You should check that the first dim of your image (or slice) is an odd number'
    return left_slice, right_slice


# ----------------------------------------------------------------------------------------------------------------------
def show(coord_projected_img, pca, target):
    # Retrieving projected image from the mean image & its coordinates
    import copy

    img_reducted = copy.copy(pca.mean_image)
    for i in range(0, coord_projected_img.shape[0]):
        img_reducted += int(coord_projected_img[i][0]) * pca.W.T[i].reshape(pca.N, 1)

    if param.split_data:
        n = int(sqrt(pca.N * 2))
    else:
        n = int(sqrt(pca.N))
    if param.split_data:
        imgplot = plt.imshow(pca.mean_image.reshape(n, n / 2))
    else:
        imgplot = plt.imshow(pca.mean_image.reshape(n, n))
    imgplot.set_interpolation('nearest')
    imgplot.set_cmap('gray')
    plt.title('Mean Image')
    plt.show()
    if param.split_data:
        imgplot = plt.imshow(target.reshape(n, n / 2))
    else:
        imgplot = plt.imshow(target.reshape(n, n))
    imgplot.set_interpolation('nearest')
    #imgplot.set_cmap('gray')
    plt.title('Original Image')
    plt.show()
    if param.split_data:
        imgplot = plt.imshow(img_reducted.reshape(n, n / 2))
    else:
        imgplot = plt.imshow(img_reducted.reshape(n, n))
    imgplot.set_interpolation('nearest')
    #imgplot.set_cmap('gray')
    plt.title('Projected Image')
    plt.show()


# ----------------------------------------------------------------------------------------------------------------------
# This little loop save projection through several pcas with different k i.e. different number of modes
def save(dataset, list_atlas_seg):
    import scipy
    import copy

    betas = [0.6, 0.7, 0.75, 0.8, 0.82, 0.85, 0.86, 0.87, 0.88, 0.89, 0.9, 0.91, 0.92, 0.93, 0.94, 0.95]
    target = list_atlas_seg[8][0].flatten()
    for beta in betas:
        pca = PCA(dataset, beta)
        coord_projected_img = pca.project(target)
        img_reducted = copy.copy(pca.mean_image)
        n = int(sqrt(pca.N * 2))
        for i in range(0, coord_projected_img.shape[0]):
            img_reducted += int(coord_projected_img[i][0]) * pca.W.T[i].reshape(pca.N, 1)
        scipy.misc.imsave("/home/django/aroux/Desktop/pca_modesInfluence/" + str(pca.kept) + "modes.jpeg",
                          img_reducted.reshape(n, n / 2))

#TODO: write a function to save images, see if already exist in msct_image ...
def save_square_image(im_array, im_name):
    import scipy
    #im = Image(np_array=im_array)
    if im_array.shape[1] == None:
        n = int(sqrt(im_array.shape[0]))
        im = im_array.reshape(n,n)
    else:
        im = im_array
    scipy.misc.imsave(im_name + " .nii.gz", im )

# ----------------------------------------------------------------------------------------------------------------------
# To apply a rigid transformation defined by tx, ty and theta to an image, with tx, ty, the translation along x and y and theta the rotation angle
def apply_2D_rigid_transformation(matrix, tx, ty, theta):
    from math import cos
    from math import sin
    xlim, ylim = matrix.shape
    transformed_im = np.zeros((xlim,ylim))
    for i,row in enumerate(matrix):
        for j,pixel_value in enumerate(row):
            #rotation
            x = i*cos(theta) + j*sin(theta)
            y = -i*sin(theta) + j*cos(theta)

            x = fabs(x)
            y = fabs(y)
            #translation
            x += tx
            y += ty
            if x < xlim and x >= 0 and y < ylim and y >= 0:
                transformed_im[x,y] = pixel_value
    return transformed_im

#TODO: replace apply_2D_rigid_transformation() by apply_ants_2D_rigid_transformation() using ants
'''
def apply_ants_2D_rigid_transformation():
    status,output = sct.run('sct_antsRegistration ')
'''

# ----------------------------------------------------------------------------------------------------------------------
# Kronecker delta function
def kronecker_delta(x, y):
    if x == y:
        return 1
    else:
        return 0


########################################################################################################################
######-------------------------------------------------  MAIN   --------------------------------------------------######
########################################################################################################################

if __name__ == "__main__":
    param = Param()

    if param.debug:
        print '\n*** WARNING: DEBUG MODE ON ***\n'
        fname_input = param.path_dictionary + "/errsm_34.nii.gz"
        fname_input = param.path_dictionary + "/errsm_34_seg_in.nii.gz"
    else:
        param_default = Param()

        # Initialize the parser
        parser = Parser(__file__)
        parser.usage.set_description('Project all the input image slices on a PCA generated from set of t2star images')
        parser.add_option(name="-i",
                          type_value="file",
                          description="T2star image you want to project",
                          mandatory=True,
                          example='t2star.nii.gz')
        parser.add_option(name="-dic",
                          type_value="folder",
                          description="Path to the dictionary of images",
                          mandatory=True,
                          example='/home/jdoe/data/dictionary')
        parser.add_option(name="-gm",
                          type_value="int",
                          description="1 will include the gray matter data, default is 0",
                          mandatory=False,
                          example='1')
        parser.add_option(name="-split",
                          type_value="int",
                          description="1 will split all images from dictionary in the right-left direction in order to have more dataset for the PCA",
                          mandatory=False,
                          example='0')
        parser.add_option(name="-v",
                          type_value="int",
                          description="verbose",
                          mandatory=False,
                          example='1')

        arguments = parser.parse(sys.argv[1:])
        fname_input = arguments["-i"]
        param.path_dictionary = arguments["-dic"]

        if "-gm" in arguments:
            param.include_GM = arguments["-gm"]
        if "-split" in arguments:
            param.split_data = arguments["-split"]
        if "-v" in arguments:
            param.verbose = arguments["-v"]


    # build the appearance model
    appearance_model = AppearanceModel(param=param)

    '''
    sct.printv('\nShowing the PCA space ...')
    appearance_model.pca.show(split=param.split_data)
    '''

    # construct target image
    target_image = Image(fname_input)
    if param.split_data:
        splited_target = []
        for slice in target_image.data:
            left_slice, right_slice = split(slice)
            splited_target.append(left_slice)
            splited_target.append(right_slice)
        target_image = Image(np.asarray(splited_target))


    #build a rigid registration
    rigid_reg = RigidRegistration(appearance_model, target_image=target_image)


    sct.printv('\nPloting Omega ...')
    rigid_reg.plot_omega()

    '''
    sct.printv('\nShowing the projected target ...')
    rigid_reg.show_projected_target()
    '''
