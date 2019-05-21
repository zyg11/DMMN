#  #!/usr/bin/env python
#   Copyright (c) 2019. ShiJie Sun at the Chang'an University
#   This work is licensed under the terms of the Creative Commons Attribution-NonCommercial-ShareAlike 3.0 License.
#   For a copy, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#   Author: shijie Sun
#   Email: shijieSun@chd.edu.cn
#   Github: www.github.com/shijieS
#

import numpy as np
from .motion_model import MotionModel
from dataset.utils.common import get_cx_cy_w_h
import torch
import scipy
from scipy.optimize import curve_fit
from tqdm import trange
np.seterr(divide='ignore', invalid='ignore')
import warnings
warnings.simplefilter('ignore', np.RankWarning)
warnings.simplefilter('ignore', np.ComplexWarning)
warnings.filterwarnings('ignore', "Intel MKL ERROR")
warnings.filterwarnings('ignore', "OptimizeWarning")

class MotionModelQuadratic(MotionModel):
    """ Perspective Motion Model :math:`f(t) = (at + b) / (ct + 1)`

    * :math:`x_c(t) = (a_0 t + a_1) / (b_2 t + 1)`
    * :math:`y_c(t) = (b_0 t + b_1) / (b_2 t + 1)`
    * :math:`w_c(t) = (c_0 t + c_1) / (c_2 t + 1)`
    * :math:`h_c(t) = (d_0 t + d_1) / (d_2 t + 1)`
    """

    def __init__(self, parameters=None):
        """
        Init by a parameters, where parameters' shape is (4, 3)
        :param parameters: a parameter whose shape is (4, 3)
        """
        super(MotionModelQuadratic, self).__init__(12)
        self.parameters = parameters

    @staticmethod
    def model_func(x, p0, p1, p2):
        return p2*x*x + p1*x + p0

    @staticmethod
    def model_func_torch(x, p0, p1, p2):
        return p2*x*x + p1*x + p0

    def fit(self, bboxes, times=None):
        if times is None:
            times = range(len(bboxes))

        res = get_cx_cy_w_h(bboxes)
        res = np.clip(res, a_min=1e-8, a_max=None)
        x = times
        parameters = []
        # curve_fit(MotionModelPerspective.model_func_all, x, np.log(res))
        try:
            p2 = 0
            for i, y in enumerate(res):
                param = curve_fit(
                    MotionModelQuadratic.model_func,
                    x, np.log(y),
                    bounds=([0, -0.1, 0], [np.inf, 1.1, 3]))[0]
                parameters += [
                    [param[0], param[1], param[2]]
                ]
            self.parameters = np.array(parameters)
        except:
            self.parameters = None

        return self.parameters


    def get_bbox_by_frame(self, time):
        p = self.parameters
        cx_cy_w_h = np.exp(MotionModelQuadratic.model_func(time, p[:, 0], p[:, 1], p[:, 2]))
        cx = cx_cy_w_h[0]
        cy = cx_cy_w_h[1]
        w = cx_cy_w_h[2]
        h = cx_cy_w_h[3]
        return np.array([cx - w/2.0, cy - h/2.0, cx + w/2.0, cy + h/2.0])

    def get_bbox_by_frames(self, times):
        """
        Get the bbox by a set of times
        :param times: a set of times with shape (n, ) where n is the length of time
        :return: boxes generated by the parameter and times, i.e. [16, 4] where 16 is the length of time and 4 is the (l, t, r, b)
        """
        t = np.tile(times[:, None], (1, self.parameters.shape[0]))
        p = np.tile(self.parameters[None, :, :], (times.shape[0], 1, 1))

        cx_cy_w_h = np.exp(MotionModelQuadratic.model_func(t, p[:, :, 0], p[:, :, 1], p[:, :, 2]))

        cx_cy_w_h[np.sum(np.isnan(cx_cy_w_h), axis=1) > 0, :] = np.zeros((4))

        bbox = np.concatenate([cx_cy_w_h[:, :2] - cx_cy_w_h[:, 2:] / 2., cx_cy_w_h[:, :2] + cx_cy_w_h[:, 2:] / 2.], axis=1)
        return bbox

    @staticmethod
    def get_invalid_params():
        return np.zeros((4, 3))

    @staticmethod
    def get_invalid_box():
        return np.ones((4))

    @staticmethod
    def get_num_parameter():
        return 12

    @staticmethod
    def get_parameters(bboxes_with_overlap_class, times, invalid_node_rate):
        """
        Get the parameter of boxes.
        :param bboxes: (N_f, N_t, 4)
        :param times: Times indexes, N_f
        :param invalid_node_rate: the threshold for cacluate the parameters
        :returns: parameters: (TrackId, ParameterData)
                  motion_possibility: (trackId, possibility)

        """
        parameters = list()
        p_e = bboxes_with_overlap_class[:, :, 4]
        p_c = bboxes_with_overlap_class[:, :, 5].max(axis=0)
        bboxes = bboxes_with_overlap_class[:, :, :4]
        frame_num, track_num, _ = bboxes.shape
        mm = MotionModelQuadratic()
        for i in range(track_num):
            bbs = bboxes[:, i, :]
            bbox_mask = np.logical_and(np.sum(bbs, axis=1) > 0, p_e[:, i] > 0)

            param = mm.fit(bbs[bbox_mask, :], times[bbox_mask])
            if param is None:
                param = MotionModelQuadratic.get_invalid_params()
                p_c[i] = 0
            parameters += [param]
            p_e[:, i] = bbox_mask

        # p_e = np.stack(p_e, axis=1)
        # p_c = np.array(p_c)
        parameters = np.stack(parameters, axis=0)
        return parameters, p_e, p_c

    @staticmethod
    def get_str(parameters):
        p = parameters[0, :]
        return "x = {:0.2f}t^2+{:0.2f}t+{:0.2f}".format(p[0], p[1], p[2])

    @staticmethod
    def get_bbox_by_frames_pytorch(parameters, times):
        p = parameters[:, None, :, :, :].expand(parameters.shape[0], times.shape[1], *parameters.shape[1:4])
        t = times[:, :, None, None].expand(*times.shape[:2], *p.shape[2:4])
        p0 = p[:, :, :, :, 0]
        p1 = p[:, :, :, :, 1]
        p2 = p[:, :, :, :, 2]

        bboxes = MotionModelQuadratic.model_func_torch(t, p0, p1, p2)


        # I cannot use the following setence for the inplace operation.
        # Acutally, it's so user unfriendly.
        # bboxes[torch.isnan(bboxes.sum(dim=3)), :] = 0
        # nan_mask = torch.isnan(bboxes.sum(dim=3))[:, :, :, None].expand_as(bboxes)
        # #
        # bboxes = torch.where(nan_mask, torch.zeros_like(bboxes), bboxes)

        # bboxes[:, :, :, 2:].clamp_(min=0, max=2)


        # times_1 = torch.stack([torch.pow(times, 2), torch.pow(times, 1), torch.pow(times, 0)], dim=2)
        # times_1 = times_1.permute([1, 0, 2])[:, :, None, None, :]
        # parameters_1 = torch.sum((parameters * times_1.float()).permute([1, 0, 2, 3, 4]), dim=4)

        return bboxes

    @staticmethod
    def get_bbox_by_frames_without_batch_pytorch(parameter, time):
        p = parameter.expand(time.shape[0], *parameter.shape).float()
        t = time[:, None, None].expand(p.shape[:-1]).float()
        p0 = p[:, :, :, 0]
        p1 = p[:, :, :, 1]
        p2 = p[:, :, :, 2]

        bboxes = MotionModelQuadratic.model_func_torch(t, p0, p1, p2)

        return bboxes

