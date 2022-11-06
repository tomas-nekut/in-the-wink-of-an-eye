from base64 import encode
import cv2
from scipy import interpolate
import numpy as np
from face_landmarks import FaceLandmarksDetector
import face_recognition as fr
from tqdm import tqdm
from PIL import Image

class FaceAnimator():
    
    def __init__(self, face_example="face_example.jpg", teeth="teeth.jpg", motion_vectors="motion_vectors.npy"):
        self.__face_example_encoding = fr.face_encodings(fr.load_image_file(face_example))
        self.__teeth = cv2.imread(teeth)
        self.__motion_vectors = np.load(motion_vectors)
        self.__face_landmarks_detector = FaceLandmarksDetector()

    # gets src_path to an image, perform animation and saves animated image to dst_path
    # return True if any animation was possible in source image
    def process(self, src_path, dst_path):
        # detect faces, find face for animation (same id as given face example) and animate it
        img = fr.load_image_file(src_path)
        for location, encoding in zip(fr.face_locations(img),fr.face_encodings(img)):
            if not fr.compare_faces([self.__face_example_encoding], encoding)[0]:
                break
            img = cv2.imread(src_path)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            # extend copped region
            location = self.__extend_location(location, img.shape)
            # cropp
            img_cropped = self.__cropp(img, location) 
            # animate
            frames_cropped = self.__animate_image(img_cropped)
            # place cropped animated frames into original image
            frames = [ self.__place(img, frame_cropped, location) for frame_cropped in frames_cropped ]
            # generate output GIF file
            frames[0].save(dst_path, format="GIF", append_images=frames, save_all=True, duration=100, loop=0)
            return True
        # no face suitable for animation found
        return False

    def __extend_location(self, location, img_shape):
        width, height = location[1]-location[3], location[2]-location[0]
        location = int(location[0]-height*0.5), int(location[1]+width*0.2), int(location[2]+height*0.2), int(location[3]-width*0.2)
        location = max(0,location[0]), min(img_shape[1],location[1]), min(img_shape[0],location[2]), max(0,location[3])
        return location

    def __cropp(self, img, location):
        return img[location[0]:location[2], location[3]:location[1]]

    def __place(self, img, patch, location):
        img = img.copy()
        img[location[0]:location[2], location[3]:location[1]] = patch
        return img

    # mapping from input to target image is described by set of source point -> destination point pairs 
    def __remap_image(self, img, src_points, dst_points):
        # interpolate source point for each pixel of the image
        f_x = interpolate.LinearNDInterpolator(dst_points, src_points[:,0])
        f_y = interpolate.LinearNDInterpolator(dst_points, src_points[:,1])
        x = f_x(*np.meshgrid(np.arange(img.shape[1]), np.arange(img.shape[0]))).astype(np.float32)
        y = f_y(*np.meshgrid(np.arange(img.shape[1]), np.arange(img.shape[0]))).astype(np.float32)
        # transform image
        remaped_img = cv2.remap(img, x, y, interpolation=cv2.INTER_LINEAR, borderValue=0, borderMode=cv2.BORDER_CONSTANT) 
        return remaped_img

    # 
    def __add_teeth(self, img, landmarks):
        teeth = cv2.imread("teeth.jpg")
        teeth = cv2.cvtColor(teeth, cv2.COLOR_BGR2RGB)
        teeth = cv2.resize(teeth, dsize=(img.shape[1],img.shape[0]))
        # transform teeth image to match mouth position of face in original image
        # find part of teeth line that is visible given view angle
        teeth_line_start = landmarks.get_teeth_line()[:,0].argmin()
        teeth_line_end = landmarks.get_teeth_line()[:,0].argmax() + 1 
        # find source points of transformation 
        # src points are nelineary positioned to compensate for frontal teeth image (not panoramatic)
        src_points = np.linspace(0, 1, len(landmarks.get_teeth_line()))  
        root = lambda x: np.sign(x) * (abs(x)**(0.7))
        src_points = ((root(2*src_points-1)))*(1/2)+(1/2)
        src_points *= teeth.shape[1]
        src_points = src_points.astype(np.int32)
        src_points = src_points[teeth_line_start:teeth_line_end]
        src_points = np.expand_dims(src_points, axis=1)
        src_points = np.hstack([src_points, np.zeros_like(src_points)])
        # upper, middle, lower teeth line
        upper_src_points, middle_src_points, lower_src_points = src_points.copy(),src_points.copy(),src_points.copy()
        upper_src_points[:,1] = 0
        middle_src_points[:,1] = int(teeth.shape[0]/2)
        lower_src_points[:,1] = teeth.shape[0]
        src_points = np.vstack([upper_src_points,middle_src_points,lower_src_points])
        # find destination points of transformation
        upper_dst_points = landmarks.get_teeth_line('upper')[teeth_line_start:teeth_line_end].to_XY()
        middle_dst_points = landmarks.get_teeth_line('middle')[teeth_line_start:teeth_line_end].to_XY()
        lower_dst_points = landmarks.get_teeth_line('lower')[teeth_line_start:teeth_line_end].to_XY()
        dst_points = np.vstack([upper_dst_points,middle_dst_points,lower_dst_points])
        # transform teeth img using source points -> destination points mapping
        remaped_teeth = self.__remap_image(teeth, src_points, dst_points) 
        # outside mapping region fill with original image 
        target_image = np.where(remaped_teeth != 0, remaped_teeth, img)
        return target_image

    def __fill_eye_mouth_with_black(self, img, landmarks):
        poly = [landmarks.get_left_eye_outline().to_XY().astype(int), 
                landmarks.get_right_eye_outline().to_XY().astype(int), 
                landmarks.get_mouth_outline().to_XY().astype(int)]
        img = cv2.fillPoly(img, pts=poly, color=(0, 0, 0))  
        return img

    def __animate_image(self, img):
        landmarks = self.__face_landmarks_detector.process(img)
        background = self.__add_teeth(img, landmarks)
        img = self.__fill_eye_mouth_with_black(img, landmarks)
        frames = []
        frame_rate = 8
        for vectors in tqdm(np.load("motion_vectors.npy")[::int(24/frame_rate)]):
            translated_landmarks = landmarks.translate(vectors)
            remaped_img = self.__remap_image(img, landmarks.get_mesh().to_XY(), translated_landmarks.get_mesh().to_XY())
            remaped_img = self.__fill_eye_mouth_with_black(remaped_img, translated_landmarks)  
            result = np.where(remaped_img != 0, remaped_img, background)
            frames.append(Image.fromarray(result))   
        return frames


