import argparse
import base64
import json
import multiprocessing
import os
import sys
import time
from multiprocessing import Pool, Queue

import numpy as np
import tensorflow as tf
from tensorflow.python import debug as tfdbg
from tensorflow.python.client import timeline

from utils import label_map_util
from utils import visualization_utils as vis_util

from utils.caffe_classes import class_names
from tensorflow.python.client import timeline

#TODO: Make this a spaghetti code class-based
CWD_PATH = os.getcwd()
LOGDIR = '/tmp/tensorboard'

HALT_SIGNAL = False

options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
run_metadata = tf.RunMetadata()


# config = tf.ConfigProto(log_device_placement=True)
config = tf.ConfigProto()
config.gpu_options.allow_growth = True

# Path to frozen classification graph. This is the actual model that is used for the object classification.``
MODEL_NAME = 'alexnet'
MODEL_DIR = 'frozen_models'

PARTITION_NAME = 'pool1'

OUTPUT_NAME = 'Softmax'


PATH_TO_CKPT = os.path.join(CWD_PATH, MODEL_DIR, MODEL_NAME, 'alexnet_frozen.pb')
PATH_TO_PARTN = os.path.join(CWD_PATH, MODEL_DIR, MODEL_NAME)
# List of the strings that is used to add correct label for each box.
PATH_TO_LABELS = os.path.join(CWD_PATH, 'data', 'imagenet_comp_graph_label_strings.txt')
NUM_CLASSES = 90


partitions_dict = {}

def readPartitionData():
        with open(os.path.join(PATH_TO_PARTN, 'alexnet_partitions.txt'), 'r') as f:

            partitions = f.readlines()
            partitions = [x.strip().split(',') for x in partitions]

            for x in partitions:
                partitions_dict[x[0]] = x[1:len(x)]

            for x, y in partitions_dict.items():
                partitions_dict[x] = list(map(int, y))

            for x, y in partitions_dict.items():
                pass

            f.close()
        print(type(partitions_dict.get('Placeholder')))

def convert_keys_to_string(dictionary):
    """Recursively converts dictionary keys to strings."""
    if not isinstance(dictionary, dict):
        return dictionary
    return dict((str(k), convert_keys_to_string(v)) for k, v in dictionary.items())

def classify_objects(frame, sess, classification_graph):

    input_data = frame.getImageData()

    with tf.device('/device:GPU:0'):
        input_tensor = classification_graph.get_tensor_by_name(PARTITION_NAME + ':0')
        classifications = classification_graph.get_tensor_by_name(OUTPUT_NAME + ':0')

        classifications = sess.run(classifications, feed_dict={input_tensor: input_data}, options=options, run_metadata=run_metadata)
        frame.deleteRawImgData()

        ind = np.argpartition(classifications[0], -3)[-3:]
        sorted_ind = ind[np.argsort(classifications[0,ind])]
        frame.detected_objects = [class_names[indx] for indx in sorted_ind] 
        frame.confidences = (classifications[0, sorted_ind]).tolist()
    return frame

def detect_objects(image_np, sess, detection_graph):
    # Expand dimensions since the model expects images to have shape: [1, None, None, 3]
    image_np_expanded = np.expand_dims(image_np, axis=0) #TODO: Make if sstatemet for YOLO Here
    image_tensor = detection_graph.get_tensor_by_name('image_tensor:0')

    # Each box represents a part of the image where a particular object was detected.
    boxes = detection_graph.get_tensor_by_name('detection_boxes:0')
    # masks = detection_graph.get_tensor_by_name('detection_masks:0')

    # Each score represent how level of confidence for each of the objects.
    # Score is shown on the result image, together with the class label.
    scores = detection_graph.get_tensor_by_name('detection_scores:0')
    classes = detection_graph.get_tensor_by_name('detection_classes:0')
    num_detections = detection_graph.get_tensor_by_name('num_detections:0')

    # Actual detection.
    (boxes, scores, classes, num_detections) = sess.run([boxes, scores, classes, num_detections], feed_dict={image_tensor: image_np_expanded}, options=options, run_metadata=run_metadata)


    detection_dict = vis_util.create_detection_dict(
        np.squeeze(boxes),
        np.squeeze(classes).astype(np.int32),
        np.squeeze(scores),
        category_index,
        use_normalized_coordinates=True,
        line_thickness=8, min_score_thresh=0.5)

    detection_dict_annotated = {}
    detection_dict_annotated = [{"object_location": i, "object_data": j} for i, j in detection_dict.items()]
    detection_dict_json = json.dumps(detection_dict_annotated)
    return detection_dict_json


def worker(input_q, output_q,):

    # Load a (frozen) Tensorflow model into memory.
    # print(">>Loading Frozen Graph")
    with tf.device('/device:GPU:0'):
        classification_graph = tf.Graph()
        with classification_graph.as_default():
            od_graph_def = tf.GraphDef()
            with tf.gfile.FastGFile(PATH_TO_CKPT, 'rb') as fid:
                serialized_graph = fid.read()
                od_graph_def.ParseFromString(serialized_graph)
                tf.import_graph_def(od_graph_def, name='')
            sess = tf.Session(graph=classification_graph, config=config)  #config enable for JIT
    try:
        while 1:
            try:
                frame = input_q.get_nowait()
                '''
                Returns Frame object
                '''
                output_q.put(classify_objects(frame, sess, classification_graph))
            except:
                continue
    except KeyboardInterrupt:
        print("closing session...")
        sess.close()
