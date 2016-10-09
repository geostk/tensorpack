#!/usr/bin/env python2
# -*- coding: UTF-8 -*-
# File: image_sample.py
# Author: Yuxin Wu <ppwwyyxx@gmail.com>

import tensorflow as tf

from ._common import layer_register

__all__ = ['ImageSample']

# XXX TODO ugly.
# really need to fix this after tensorflow supports advanced indexing
# See github:tensorflow#418,#206
def sample(img, coords, borderMode):
    """
    :param img: bxhxwxc
    :param coords: bxh2xw2x2 (y, x) floating point (but is actually holding integer)
    :return: bxh2xw2xc image
    """
    orig_coords = tf.cast(coords, tf.int32)
    shape = img.get_shape().as_list()[1:]
    shape2 = coords.get_shape().as_list()[1:3]
    max_coor = tf.constant([shape[0] - 1, shape[1] - 1], dtype=tf.int32)

    # clip_by_value actually supports broadcasting
    coords = tf.clip_by_value(orig_coords, 0, max_coor)  # borderMode==repeat

    w = shape[1]
    coords = tf.reshape(coords, [-1, 2])
    coords = tf.matmul(coords, tf.constant([[w], [1]]))
    coords = tf.reshape(coords, [-1] + shape2)
    # bxh2xw2

    batch_add = tf.range(tf.shape(img)[0]) * (shape[0] * shape[1])
    batch_add = tf.reshape(batch_add, [-1, 1, 1])   #bx1x1

    flat_coords = coords + batch_add

    img = tf.reshape(img, [-1, shape[2]])   #bhw x c
    sampled = tf.gather(img, flat_coords)

    if borderMode == 'constant':
        mask = tf.less_equal(orig_coords, max_coor)
        mask2 = tf.greater_equal(orig_coords, 0)
        mask = tf.logical_and(mask, mask2)   #bxh2xw2x2
        mask = tf.reduce_all(mask, [3]) # bxh2xw2 boolean
        mask = tf.expand_dims(mask, 3)
        sampled = sampled * tf.cast(mask, tf.float32)
    return sampled

@layer_register()
def ImageSample(inputs, borderMode='repeat'):
    """
    Sample the template image, using the given coordinate, by bilinear interpolation.
    It mimics the same behavior described in:
    `Spatial Transformer Networks <http://arxiv.org/abs/1506.02025>`_.

    :param input: [template, mapping]. template of shape NHWC.
        mapping of shape NHW2, where each pair of the last dimension is a (y, x) real-value
        coordinate.
    :param borderMode: either 'repeat' or 'constant' (0)
    :returns: a NHWC output tensor.
    """
    template, mapping = inputs
    assert template.get_shape().ndims == 4 and mapping.get_shape().ndims == 4
    assert borderMode in ['repeat', 'constant']

    mapping = tf.maximum(mapping, 0.0)
    lcoor = tf.floor(mapping)
    ucoor = lcoor + 1

    diff = mapping - lcoor
    neg_diff = 1.0 - diff   #bxh2xw2x2

    lcoory, lcoorx = tf.split(3, 2, lcoor)
    ucoory, ucoorx = tf.split(3, 2, ucoor)

    lyux = tf.concat(3, [lcoory, ucoorx])
    uylx = tf.concat(3, [ucoory, lcoorx])

    diffy, diffx = tf.split(3, 2, diff)
    neg_diffy, neg_diffx = tf.split(3, 2, neg_diff)

    #prod = tf.reduce_prod(diff, 3, keep_dims=True)
    #diff = tf.Print(diff, [tf.is_finite(tf.reduce_sum(diff)), tf.shape(prod),
                          #tf.reduce_max(diff), diff], summarize=50)

    return tf.add_n([sample(template, lcoor, borderMode) * neg_diffx * neg_diffy,
           sample(template, ucoor, borderMode) * diffx * diffy,
           sample(template, lyux, borderMode) * neg_diffy * diffx,
           sample(template, uylx, borderMode) * diffy * neg_diffx], name='sampled')

from ._test import TestModel
class TestSample(TestModel):
    def test_sample(self):
        import numpy as np
        h, w = 3, 4
        def np_sample(img, coords):
            # a reference implementation
            coords = np.maximum(coords, 0)
            coords = np.minimum(coords,
                                np.array([img.shape[1]-1, img.shape[2]-1]))
            xs = coords[:,:,:,1].reshape((img.shape[0], -1))
            ys = coords[:,:,:,0].reshape((img.shape[0], -1))

            ret = np.zeros((img.shape[0], coords.shape[1], coords.shape[2],
                            img.shape[3]), dtype='float32')
            for k in range(img.shape[0]):
                xss, yss = xs[k], ys[k]
                ret[k,:,:,:] = img[k,yss,xss,:].reshape((coords.shape[1],
                                                         coords.shape[2], 3))
            return ret

        bimg = np.random.rand(2, h, w, 3).astype('float32')

        #mat = np.array([
            #[[[1,1], [1.2,1.2]], [[-1, -1], [2.5, 2.5]]],
            #[[[1,1], [1.2,1.2]], [[-1, -1], [2.5, 2.5]]]
        #], dtype='float32')  #2x2x2x2
        mat = (np.random.rand(2, 5, 5, 2) - 0.2) * np.array([h + 3, w + 3])
        true_res = np_sample(bimg, np.floor(mat + 0.5).astype('int32'))

        inp, mapping = self.make_variable(bimg, mat)
        output = sample(inp, tf.cast(tf.floor(mapping+0.5), tf.int32))
        res = self.run_variable(output)

        self.assertTrue((res == true_res).all())

if __name__ == '__main__':
    import cv2
    import numpy as np
    import sys
    im = cv2.imread('cat.jpg')
    im = im.reshape((1,) + im.shape).astype('float32')
    imv = tf.Variable(im)

    h, w = 300, 400
    mapping = np.zeros((1, h, w, 2), dtype='float32')
    diff = 2000
    for x in range(w):
        for y in range(h):
            mapping[0,y,x,:] = np.array([y-diff+0.4, x-diff+0.5])

    mapv = tf.Variable(mapping)
    output = ImageSample('sample', [imv, mapv])
    sess = tf.Session()
    sess.run(tf.initialize_all_variables())

    out = sess.run(tf.gradients(tf.reduce_sum(output), mapv))
    #out = sess.run(output)
    print(out[0].min())
    print(out[0].max())
    print(out[0].sum())

    out = sess.run([output])[0]
    im = out[0]
    cv2.imwrite('sampled.jpg', im)


