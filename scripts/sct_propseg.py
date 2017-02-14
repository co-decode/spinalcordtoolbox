#!/usr/bin/env python
#########################################################################################
#
# Parser for PropSeg binary.
#
# ---------------------------------------------------------------------------------------
# Copyright (c) 2015 Polytechnique Montreal <www.neuro.polymtl.ca>
# Authors: Benjamin De Leener
# Modified: 2015-03-03
#
# About the license: see the file LICENSE.TXT
#########################################################################################

import os
import shutil
import sys
from glob import glob

import numpy as np
import scipy

import msct_image
import msct_parser
import sct_convert
import sct_image
import sct_label_utils
import sct_utils as sct


def check_and_correct_segmentation(fname_segmentation, fname_centerline, threshold_distance=5.0, remove_temp_files=1, verbose=0):
    """
    This function takes the outputs of isct_propseg (centerline and segmentation) and check if the centerline of the
    segmentation is coherent with the centerline provided by the isct_propseg, especially on the edges (related
    to issue #1074).
    Args:
        fname_segmentation: filename of binary segmentation
        fname_centerline: filename of binary centerline
        threshold_distance: threshold, in mm, beyond which centerlines are not coherent
        verbose:

    Returns: None
    """
    sct.printv('\nCheck consistency of segmentation...', verbose)
    # creating a temporary folder in which all temporary files will be placed and deleted afterwards
    path_tmp = sct.tmp_create(verbose=verbose)
    sct_convert.convert(fname_segmentation, path_tmp + 'tmp.segmentation.nii.gz', squeeze_data=False, verbose=0)
    sct_convert.convert(fname_centerline, path_tmp + 'tmp.centerline.nii.gz', squeeze_data=False, verbose=0)

    # go to tmp folder
    os.chdir(path_tmp)

    # convert segmentation image to RPI
    im_input = msct_image.Image('tmp.segmentation.nii.gz')
    image_input_orientation = sct_image.orientation(im_input, get=True, verbose=False)
    sct.run('sct_image -i tmp.segmentation.nii.gz -setorient RPI -o tmp.segmentation_RPI.nii.gz', verbose)
    sct.run('sct_image -i tmp.centerline.nii.gz -setorient RPI -o tmp.centerline_RPI.nii.gz', verbose)

    # go through segmentation image, and compare with centerline from propseg
    im_seg = msct_image.Image('tmp.segmentation_RPI.nii.gz')
    im_centerline = msct_image.Image('tmp.centerline_RPI.nii.gz')

    # Get size of data
    sct.printv('\nGet data dimensions...', verbose)
    nx, ny, nz, nt, px, py, pz, pt = im_seg.dim

    # extraction of centerline provided by isct_propseg and computation of center of mass for each slice
    # the centerline is defined as the center of the tubular mesh outputed by propseg.
    centerline, key_centerline = {}, []
    for i in range(nz):
        slice = im_centerline.data[:, :, i]
        if np.any(slice):
            x_centerline, y_centerline = scipy.ndimage.measurements.center_of_mass(slice)
            centerline[str(i)] = [x_centerline, y_centerline]
            key_centerline.append(i)

    # for each slice of the segmentation, check if only one object is present. If not, remove the slice from segmentation.
    # If only one object (the spinal cord) is present in the slice, check if its center of mass is close to the centerline of isct_propseg.
    slices_to_remove = [False] * nz  # flag that decides if the slice must be removed
    for i in range(nz):
        # extraction of slice
        slice = im_seg.data[:, :, i]
        label_objects, nb_labels = scipy.ndimage.label(slice)  # count binary objects in the slice
        if nb_labels > 1:  # if there is more that one object in the slice, the slice is removed from the segmentation
            slices_to_remove[i] = True
        elif nb_labels == 1:  # check if the centerline is coherent with the one from isct_propseg
            x_centerline, y_centerline = scipy.ndimage.measurements.center_of_mass(slice)
            slice_nearest_coord = min(key_centerline, key=lambda x:abs(x-i))
            coord_nearest_coord = centerline[str(slice_nearest_coord)]
            distance = np.sqrt(((x_centerline - coord_nearest_coord[0]) * px) ** 2 +
                               ((y_centerline - coord_nearest_coord[1]) * py) ** 2 +
                               ((i - slice_nearest_coord) * pz) ** 2)

            if distance >= threshold_distance:  # threshold must be adjusted, default is 5 mm
                slices_to_remove[i] = True

    # Check list of removal and keep one continuous centerline (improve this comment)
    # Method:
    # starting from mid-centerline (in both directions), the first True encountered is applied to all following slices
    slice_to_change = False
    for i in range(nz / 2, nz):
        if slice_to_change:
            slices_to_remove[i] = True
        elif slices_to_remove[i]:
            slices_to_remove[i] = True
            slice_to_change = True
    slice_to_change = False
    for i in range(nz / 2, -1, -1):
        if slice_to_change:
            slices_to_remove[i] = True
        elif slices_to_remove[i]:
            slices_to_remove[i] = True
            slice_to_change = True

    for i in range(nz):
        # remove the slice
        if slices_to_remove[i]:
            im_seg.data[:, :, i] *= 0

    # saving the image
    im_seg.setFileName('tmp.segmentation_RPI_c.nii.gz')
    im_seg.save()

    # replacing old segmentation with the corrected one
    sct.run('sct_image -i tmp.segmentation_RPI_c.nii.gz -setorient ' + image_input_orientation + ' -o ../' + fname_segmentation, verbose)

    os.chdir('..')

    # display information about how much of the segmentation has been corrected

    # remove temporary files
    if remove_temp_files:
        sct.printv("\nRemove temporary files...", verbose)
        shutil.rmtree(path_tmp, ignore_errors=True)


def get_parser():
    # Initialize the parser
    parser = msct_parser.Parser(__file__)
    parser.usage.set_description('''This program segments automatically the spinal cord on T1- and T2-weighted images, for any field of view. You must provide the type of contrast, the image as well as the output folder path.
Initialization is provided by a spinal cord detection module based on the elliptical Hough transform on multiple axial slices. The result of the detection is available as a PNG image using option -detection-display.
Parameters of the spinal cord detection are :
 - the position (in inferior-superior direction) of the initialization
 - the number of axial slices
 - the gap (in pixel) between two axial slices
 - the approximate radius of the spinal cord

Primary output is the binary mask of the spinal cord segmentation. This method must provide VTK triangular mesh of the segmentation (option -mesh). Spinal cord centerline is available as a binary image (-centerline-binary) or a text file with coordinates in world referential (-centerline-coord).
Cross-sectional areas along the spinal cord can be available (-cross).
Several tips on segmentation correction can be found on the "Correction Tips" page of the documentation while advices on parameters adjustments can be found on the "Parameters" page.
If the segmentation fails at some location (e.g. due to poor contrast between spinal cord and CSF), edit your anatomical image (e.g. with fslview) and manually enhance the contrast by adding bright values around the spinal cord for T2-weighted images (dark values for T1-weighted). Then, launch the segmentation again.''')
    parser.add_option(name="-i",
                      type_value="image_nifti",
                      description="input image.",
                      mandatory=True,
                      example="t1.nii.gz")
    parser.add_option(name="-t",
                      type_value="multiple_choice",
                      description="type of image contrast, t2: cord dark / CSF bright ; t1: cord bright / CSF dark",
                      mandatory=False,
                      deprecated=1,
                      deprecated_by="-c",
                      example=['t1','t2'])
    parser.add_option(name="-c",
                      type_value="multiple_choice",
                      description="type of image contrast, t2: cord dark / CSF bright ; t1: cord bright / CSF dark",
                      mandatory=True,
                      example=['t1','t2'])
    parser.usage.addSection("General options")
    parser.add_option(name="-ofolder",
                      type_value="folder_creation",
                      description="output folder.",
                      mandatory=False,
                      example="My_Output_Folder/",
                      default_value="")
    parser.add_option(name="-down",
                      type_value="int",
                      description="down limit of the propagation, default is 0",
                      mandatory=False)
    parser.add_option(name="-up",
                      type_value="int",
                      description="up limit of the propagation, default is the highest slice of the image",
                      mandatory=False)
    parser.add_option(name="-r",
                      type_value="multiple_choice",
                      description="remove temporary files.",
                      mandatory=False,
                      example=['0', '1'],
                      default_value='1')
    parser.add_option(name="-v",
                      type_value="multiple_choice",
                      description="1: display on, 0: display off (default)",
                      mandatory=False,
                      example=["0", "1"],
                      default_value="1")
    parser.add_option(name="-h",
                      type_value=None,
                      description="display this help",
                      mandatory=False)

    parser.usage.addSection("\nOutput options")
    parser.add_option(name="-mesh",
                      type_value=None,
                      description="output: mesh of the spinal cord segmentation",
                      mandatory=False)
    parser.add_option(name="-centerline-binary",
                      type_value=None,
                      description="output: centerline as a binary image ",
                      mandatory=False)
    parser.add_option(name="-CSF",
                      type_value=None,
                      description="output: CSF segmentation",
                      mandatory=False)
    parser.add_option(name="-centerline-coord",
                      type_value=None,
                      description="output: centerline in world coordinates",
                      mandatory=False)
    parser.add_option(name="-cross",
                      type_value=None,
                      description="output: cross-sectional areas",
                      mandatory=False)
    parser.add_option(name="-init-tube",
                      type_value=None,
                      description="output: initial tubular meshes ",
                      mandatory=False)
    parser.add_option(name="-low-resolution-mesh",
                      type_value=None,
                      description="output: low-resolution mesh",
                      mandatory=False)
    parser.add_option(name="-detect-nii",
                      type_value=None,
                      description="output: spinal cord detection as a nifti image",
                      mandatory=False)
    parser.add_option(name="-detect-png",
                      type_value=None,
                      description="output: spinal cord detection as a PNG image",
                      mandatory=False)

    parser.usage.addSection("\nOptions helping the segmentation")
    parser.add_option(name="-init-centerline",
                      type_value="image_nifti",
                      description="filename of centerline to use for the propagation, format .txt or .nii, see file structure in documentation.\nReplace filename by 'viewer' to use interactive viewer for providing centerline. Ex: -init-centerline viewer",
                      mandatory=False)
    parser.add_option(name="-init",
                      type_value="float",
                      description="axial slice where the propagation starts, default is middle axial slice",
                      mandatory=False)
    parser.add_option(name="-init-mask",
                      type_value="image_nifti",
                      description="mask containing three center of the spinal cord, used to initiate the propagation.\nReplace filename by 'viewer' to use interactive viewer for providing mask. Ex: -init-mask viewer",
                      mandatory=False)
    parser.add_option(name="-mask-correction",
                      type_value="image_nifti",
                      description="mask containing binary pixels at edges of the spinal cord on which the segmentation algorithm will be forced to register the surface. Can be used in case of poor/missing contrast between spinal cord and CSF or in the presence of artefacts/pathologies.",
                      mandatory=False)
    parser.add_option(name="-radius",
                      type_value="float",
                      description="approximate radius (in mm) of the spinal cord, default is 4",
                      mandatory=False)
    parser.add_option(name="-detect-n",
                      type_value="int",
                      description="number of axial slices computed in the detection process, default is 4",
                      mandatory=False)
    parser.add_option(name="-detect-gap",
                      type_value="int",
                      description="gap along Z direction (in mm) for the detection process, default is 4",
                      mandatory=False)
    parser.add_option(name="-init-validation",
                      type_value=None,
                      description="enable validation on spinal cord detection based on discriminant analysis",
                      mandatory=False)
    parser.add_option(name="-nbiter",
                      type_value="int",
                      description="stop condition: number of iteration for the propagation for both direction, default is 200",
                      mandatory=False)
    parser.add_option(name="-max-area",
                      type_value="float",
                      description="[mm^2], stop condition: maximum cross-sectional area, default is 120",
                      mandatory=False)
    parser.add_option(name="-max-deformation",
                      type_value="float",
                      description="[mm], stop condition: maximum deformation per iteration, default is 2.5",
                      mandatory=False)
    parser.add_option(name="-min-contrast",
                      type_value="float",
                      description="[intensity value], stop condition: minimum local SC/CSF contrast, default is 50",
                      mandatory=False)
    parser.add_option(name="-d",
                      type_value="float",
                      description="trade-off between distance of most promising point (d is high) and feature strength (d is low), default depend on the contrast. Range of values from 0 to 50. 15-25 values show good results, default is 10",
                      mandatory=False)
    parser.add_option(name="-distance-search",
                      type_value="float",
                      description="maximum distance of optimal points computation along the surface normals. Range of values from 0 to 30, default is 15",
                      mandatory=False)
    parser.add_option(name="-alpha",
                      type_value="float",
                      description="trade-off between internal (alpha is high) and external (alpha is low) forces. Range of values from 0 to 50, default is 25",
                      mandatory=False)
    return parser


def main(args=None):

    if not args:
        args = sys.argv[1:]
    else:
        script_name =os.path.splitext(os.path.basename(__file__))[0]
        sct.printv('{0} {1}'.format(script_name, " ".join(args)))

    # Get parser info
    parser = get_parser()
    arguments = parser.parse(args)

    fname_data = os.path.abspath(arguments["-i"])
    contrast_type = arguments["-c"]

    # Building the command
    isct_options = ' -i "%s" -t %s' % (fname_data, contrast_type)

    if "-ofolder" in arguments:
        folder_output = sct.slash_at_the_end(arguments["-ofolder"], slash=1)
    else:
        folder_output = './'
    isct_options += ' -o "%s"' % folder_output
    if not os.path.isdir(folder_output) and os.path.exists(folder_output):
        sct.printv("ERROR output directory %s is not a valid directory" % folder_output, 1, 'error')
    if not os.path.exists(folder_output):
        os.makedirs(folder_output)

    if "-down" in arguments:
        isct_options += " -down " + str(arguments["-down"])
    if "-up" in arguments:
        isct_options += " -up " + str(arguments["-up"])

    remove_temp_files = 1
    if "-r" in arguments:
        remove_temp_files = int(arguments["-r"])
    verbose = 0
    if "-v" in arguments:
        if arguments["-v"] is "1":
            verbose = 2
            isct_options += " -verbose"

    # Output options
    if "-mesh" in arguments:
        isct_options += " -mesh"
    if "-centerline-binary" in arguments:
        isct_options += " -centerline-binary"
    if "-CSF" in arguments:
        isct_options += " -CSF"
    if "-centerline-coord" in arguments:
        isct_options += " -centerline-coord"
    if "-cross" in arguments:
        isct_options += " -cross"
    if "-init-tube" in arguments:
        isct_options += " -init-tube"
    if "-low-resolution-mesh" in arguments:
        isct_options += " -low-resolution-mesh"
    if "-detect-nii" in arguments:
        isct_options += " -detect-nii"
    if "-detect-png" in arguments:
        isct_options += " -detect-png"

    # Helping options
    use_viewer = None
    if "-init-centerline" in arguments:
        if str(arguments["-init-centerline"]) == "viewer":
            use_viewer = "centerline"
        else:
            isct_options += " -init-centerline " + str(arguments["-init-centerline"])
    if "-init" in arguments:
        isct_options += " -init " + str(arguments["-init"])
    if "-init-mask" in arguments:
        if str(arguments["-init-mask"]) == "viewer":
            use_viewer = "mask"
        else:
            isct_options += " -init-mask " + str(arguments["-init-mask"])
    if "-mask-correction" in arguments:
        isct_options += " -mask-correction " + str(arguments["-mask-correction"])
    if "-radius" in arguments:
        isct_options += " -radius " + str(arguments["-radius"])
    if "-detect-n" in arguments:
        isct_options += " -detect-n " + str(arguments["-detect-n"])
    if "-detect-gap" in arguments:
        isct_options += " -detect-gap " + str(arguments["-detect-gap"])
    if "-init-validation" in arguments:
        isct_options += " -init-validation"
    if "-nbiter" in arguments:
        isct_options += " -nbiter " + str(arguments["-nbiter"])
    if "-max-area" in arguments:
        isct_options += " -max-area " + str(arguments["-max-area"])
    if "-max-deformation" in arguments:
        isct_options += " -max-deformation " + str(arguments["-max-deformation"])
    if "-min-contrast" in arguments:
        isct_options += " -min-contrast " + str(arguments["-min-contrast"])
    if "-d" in arguments:
        isct_options += " -d " + str(arguments["-d"])
    if "-distance-search" in arguments:
        isct_options += " -dsearch " + str(arguments["-distance-search"])
    if "-alpha" in arguments:
        isct_options += " -alpha " + str(arguments["-alpha"])

    image_input = msct_image.Image(fname_data)
    nx, ny, nz, nt, px, py, pz, pt = image_input.dim
    if nt > 1:
        sct.printv('ERROR: your input image needs to be 3D in order to be segmented.', 1, 'error')

    path_data, file_data, ext_data = sct.extract_fname(fname_data)

    # if centerline or mask is asked using viewer
    if use_viewer:
        # make sure image is in SAL orientation, as it is the orientation used by PropSeg
        image_input_orientation = sct_image.orientation(image_input, get=True, verbose=False)
        path_fname, file_fname, ext_fname = sct.extract_fname(fname_data)
        reoriented_image_filename = 'tmp.' + sct.add_suffix(file_fname + ext_fname, "_SAL")
        path_tmp_viewer = sct.tmp_create(verbose=verbose)
        sct_image.main(['-i', fname_data,
                        '-o', os.path.join(path_tmp_viewer, reoriented_image_filename),
                        '-setorient', 'SAL',
                        '-v', '0'])

        from sct_viewer import ClickViewer
        image_input_reoriented = msct_image.Image(path_tmp_viewer + reoriented_image_filename)
        viewer = ClickViewer(image_input_reoriented)
        viewer.help_url = 'https://sourceforge.net/p/spinalcordtoolbox/wiki/correction_PropSeg/attachment/propseg_viewer.png'
        if use_viewer == "mask":
            viewer.number_of_slices = 3
            viewer.gap_inter_slice = int(10 / pz)
            if viewer.gap_inter_slice == 0:
                viewer.gap_inter_slice = 1
            viewer.calculate_list_slices()
        #else:
        #    viewer.gap_inter_slice = 3

        # start the viewer that ask the user to enter a few points along the spinal cord
        mask_points = viewer.start()

        if not mask_points and viewer.closed:
            mask_points = viewer.list_points_useful_notation

        if mask_points:
            # create the mask containing either the three-points or centerline mask for initialization
            mask_filename = sct.add_suffix(reoriented_image_filename, "_mask_viewer")

            sct_label_utils.main(["-i", os.path.join(path_tmp_viewer, reoriented_image_filename),
                                  "-create", mask_points,
                                  "-o", os.path.join(path_tmp_viewer, mask_filename)])

            # reorient the initialization mask to correspond to input image orientation
            mask_reoriented_filename = sct.add_suffix(file_fname + ext_fname, "_mask_viewer")
            sct_image.main(['-i', os.path.join(path_tmp_viewer, mask_filename),
                            '-o', os.path.join(folder_output, mask_reoriented_filename),
                            '-setorient ' + image_input_orientation,
                            '-v', '0'])

            # add mask filename to parameters string
            if use_viewer == "centerline":
                isct_options += " -init-centerline " + folder_output + mask_reoriented_filename
            elif use_viewer == "mask":
                isct_options += " -init-mask " + folder_output + mask_reoriented_filename
        else:
            sct.printv('\nERROR: the viewer has been closed before entering all manual points. Please try again.', 1,
                       type='error')

    isct_options += ' -centerline-binary'
    cmd = 'isct_propseg' + isct_options
    status, output = sct.run(cmd, verbose, error_exit='verbose')

    # check status is not 0
    if not status == 0:
        sct.printv('\nERROR: Automatic cord detection failed. Please initialize using -init-centerline or -init-mask (see help).', 1, type='error')

    # build output filename
    file_seg = file_data + "_seg" + ext_data
    fname_seg = os.path.normpath(folder_output + file_seg)

    # check consistency of segmentation
    fname_centerline = folder_output + file_data + '_centerline' + ext_data
    check_and_correct_segmentation(fname_seg, fname_centerline, threshold_distance=3.0, remove_temp_files=remove_temp_files, verbose=verbose)

    # copy header from input to segmentation to make sure qform is the same
    from sct_image import copy_header
    im_seg = msct_image.Image(fname_seg)
    im_seg = copy_header(image_input, im_seg)
    im_seg.save(data_type='int8')

    # remove temporary files
    if remove_temp_files:
        sct.printv("\nRemove temporary files...", verbose)
        if use_viewer:
            shutil.rmtree(path_tmp_viewer, ignore_errors=True)

    sct.printv('\nDone! To view results, type:', verbose)
    sct.printv("fslview "+fname_data+" "+fname_seg+" -l Red -b 0,1 -t 0.7 &\n", verbose, 'info')


if __name__ == "__main__":
    main()
