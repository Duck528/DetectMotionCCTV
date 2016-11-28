# -*- coding: utf-8 -*-


from kivy.config import Config
Config.set('graphics', 'width', '730')
Config.set('graphics', 'height', '700')

import kivy
kivy.require('1.9.1')
import numpy as np
import tempfile
import cv2
import os
import requests
import string
import random

from ffmpy import FFmpeg
from datetime import datetime
from kivy.app import App
from kivy.graphics.texture import Texture
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.gridlayout import GridLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.button import Button
from kivy.uix.listview import ListView
from kivy.clock import Clock
from kivy.uix.slider import Slider
from kivy.adapters.listadapter import ListAdapter


down_alphas = list(string.ascii_lowercase)
up_alphas = list(string.ascii_uppercase)
numbers = [str(n) for n in range(0, 10)]


def rand_str_build(str_format):
    """
    :param str_format d, u, n
    :return:
    """
    rand_str = ""
    for ch in str_format:
        if ch == 'd':
            rand_str += down_alphas[random.randint(0, len(down_alphas)-1)]
        elif ch == 'u':
            rand_str += up_alphas[random.randint(0, len(up_alphas)-1)]
        elif ch == 'n':
            rand_str += numbers[random.randint(0, len(numbers)-1)]
        else:
            rand_str += ch

    return rand_str


class VideoListView(ListView):
    def __init__(self, **kwargs):
        path = kwargs['path']
        videos = [v for v in os.listdir(path) if '.avi' in v]
        super(VideoListView, self).__init__(
            adapter=ListAdapter(data=videos, cls='ListItemButton')
        )


class MonitoringWindow(GridLayout):
    def __init__(self, cam_capture, fps, **kwargs):
        super(MonitoringWindow, self).__init__(**kwargs)
        self.rows = 2
        self.btn_play_or_stop = Button(text='Play', font_size=12)
        self.btn_control_sens = Button(text='Control Sens', font_size=12)
        self.btn_view_videos = Button(text='Monitoring', font_size=12)
        self.btn_convert_view = Button(text='Color View', font_size=12)
        self.monitoring_view = MonitoringView(cam_capture, fps, **kwargs)

        # monitoring window config setting
        # 현재 슬라이더가 화면에 보여지는 상태를 표시한다
        # True: 화면에 표시되는 상태 / False: 화면에 표시되지 않는 상태
        self.present_sens_slider = False

        # bind event to button
        self.btn_play_or_stop.bind(on_press=self._tab_btn_play_or_stop)
        self.btn_control_sens.bind(on_press=self._tab_btn_control_sens)
        self.btn_convert_view.bind(on_press=self._tab_btn_convert_view)

        wrapper_view = FloatLayout()
        wrapper_view.add_widget(self.monitoring_view)

        wrapper_nav = GridLayout(height=50, size_hint_y=None)
        wrapper_nav.cols = 4
        wrapper_nav.add_widget(self.btn_play_or_stop)
        wrapper_nav.add_widget(self.btn_control_sens)
        wrapper_nav.add_widget(self.btn_view_videos)
        wrapper_nav.add_widget(self.btn_convert_view)

        self.add_widget(wrapper_view)
        self.add_widget(wrapper_nav)

    def _tab_btn_play_or_stop(self, d):
        if self.monitoring_view.enable is True:
            self.monitoring_view.enable = False
        else:
            self.monitoring_view.enable = True

    def _tab_btn_convert_view(self, button):
        if self.monitoring_view.is_color_view is True:
            self.monitoring_view.is_color_view = False
            button.text = 'Color View'
        else:
            self.monitoring_view.is_color_view = True
            button.text = 'Black View'

    def _slider_value_changed(self, slider, value):
        self.monitoring_view.sensitivity = value

    def _tab_btn_control_sens(self, d):
        if self.present_sens_slider is True:
            self.monitoring_view.remove_widget(self.sens_slider)
            d.text = 'Control Sens'
            self.present_sens_slider = False
            return
        else:
            mv_width = self.monitoring_view.width
            mv_height = self.monitoring_view.height
            cur_sens = self.monitoring_view.sensitivity
            slider = Slider(min=10, max=25, value=cur_sens, orientation='horizontal')
            slider.width = 220
            slider.pos = (mv_width/2 - slider.width/2, mv_height/2 - slider.height/2)
            slider.bind(value=self._slider_value_changed)

            self.monitoring_view.add_widget(slider)
            self.present_sens_slider = True
            self.sens_slider = slider

            d.text = 'Hide Sens'


class MonitoringView(Image):
    def __init__(self, cam_capture, fps, **kwargs):
        super(MonitoringView, self).__init__(**kwargs)
        self.cam_capture = cam_capture
        self.fps = fps
        self.prev_img = None
        self.acc_img = None
        self.prior_detected = False
        self.counter = 150
        self.frames = list()
        self.enable = False
        self.sensitivity = 17
        self.text_pos = 100, 200
        self.url = "http://localhost:8080/cloudwatcher/api/video/upload"
        self.video_save_path = os.path.join(tempfile.gettempdir(), 'cloudwatcher')

        # 사용자한데 보여지는 화면이 컬러인지 아니면 윤곽선 화면인지 표시한다
        # True: 컬러로 있는 그대로 보여진다 / False: 윤곽선만 보여준다
        self.is_color_view = True

        # recording status label
        recording_label = Label(text='[color=ff3333]Recording[/color]', markup=True, font_size='18sp')
        recording_label.pos = (560, 530)
        recording_label.color = (1, 0, 0)
        self.status_label = recording_label
        self.present_status = False

        # motion detecting label
        detection_label = Label(text='[color=ff3333]Moving Detected[/color]', markup=True, font_size='18sp')
        detection_label.pos = (90, 480)
        self.detection_label = detection_label
        self.present_detection_label = False

        try:
            if os.path.exists(self.video_save_path) is False:
                os.mkdir(self.video_save_path)
        except IOError as e:
            print '초기화 에러: ', e
            return

        Clock.schedule_interval(self.update, 1.0 / fps)

    def save_video(self, frames):
        if len(frames) == 0:
            return None

        date = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        name = rand_str_build('ddduuunnn')
        video_path = os.path.join(self.video_save_path, date + name) + ".avi"
        print video_path
        fourcc = cv2.cv.CV_FOURCC(*'XVID')

        height, width = frames[0].shape[:2]
        recorder = None
        try:
            recorder = cv2.VideoWriter(video_path, fourcc, 20, (width, height))
            for f in frames:
                recorder.write(f)
        except RuntimeError as e:
            # 에러로그를 남긴다
            return None
        finally:
            if recorder is not None:
                recorder.release()

        print 'saved video path: ', video_path
        return video_path

    def upload_video(self, video_path):
        filename, exp = os.path.splitext(video_path)
        mp4_path = filename + '.mp4'

        try:
           ff = FFmpeg(inputs={video_path: None}, outputs={mp4_path: None})
           ff.run()
        except RuntimeError as e:
            # 에러로그를 남긴다
            return False

        # make http post to server data
        detection_time = datetime.now()
        files = {'uploadVideo': open(mp4_path, 'rb')}
        # 테스트 용으로 하드코딩한다. 추후에 사용자한데 입력받는 것으로 변경한다
        param = {
            'userId': 'illsky',
            "secretKey": 'mnvorbmanycxbtt65199',
            "detectedDate": detection_time
        }

        resp = None
        try:
            resp = requests.post(self.url, files=files, data=param)
            print resp.text
        except RuntimeError as e:
            # 에러로그를 남긴다
            print resp.text
            return False
        return True

    # detect moving object, if not detected return False
    def detect_moving(self, bg_img, img, ori_img):
        diff_img = cv2.subtract(bg_img, img)
        ret, thresh = cv2.threshold(diff_img, 50, 120, cv2.THRESH_BINARY)

        # contours, hierarchy = cv2.findContours(thresh, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        is_detected = False
        bounding_rects = []
        for cont in contours:
            approx = cv2.approxPolyDP(cont, 0.01 * cv2.arcLength(cont, True), True)
            x, y, w, h = cv2.boundingRect(cont)
            if w > 20 and h > 20:
                bounding_rects.append((x, y, w, h))
            if len(approx) >= self.sensitivity:
                is_detected = True

        if is_detected is True:
            self.counter += 2
            if self.present_detection_label is False:
                print 'here1'
                self.present_detection_label = True
                self.add_widget(self.detection_label)
        else:
            if self.present_detection_label is True:
                print 'here2'
                self.present_detection_label = False
                self.remove_widget(self.detection_label)

        if self.is_color_view is True:
            detected_img = cv2.flip(ori_img, 0)
        else:
            detected_img = np.zeros((480, 640, 3), np.uint8)
            cv2.drawContours(detected_img, contours, -1, (0, 255, 0), 3)

        for rect in bounding_rects:
            x, y, w, h = rect
            cv2.rectangle(detected_img, (x, y), (x+w, y+h), (0, 255, 0), 2)

        return is_detected, detected_img

    # read image from camera, and find background
    def read_cam(self):
        """
        카메라에서 영상을 읽고 전경과 배경을 분리하는 역할을 한다.
        영상을 학습하기 전에 bg_img=None
        :return: result, ori_img, filtered_img, bg_img
        """
        res, img = self.cam_capture.read()
        if res is False:
            print 'Camera Read Error'
            return False, None, None, None

        ori_img = img.copy()
        img = cv2.bilateralFilter(img, 9, 75, 75)
        img = cv2.flip(img, 0)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        if self.prev_img is None:
            self.prev_img = img
            self.acc_img = np.float32(img)
            return False, ori_img, None, None

        cv2.accumulateWeighted(self.prev_img, self.acc_img, 0.1)
        background_img = cv2.convertScaleAbs(self.acc_img)
        self.prev_img = img

        return True, ori_img, img, background_img

    def update(self, data):
        if self.enable is False:
            return

        print self.counter
        result, ori_img, filtered_img, bg_img = self.read_cam()
        if result is False:
            return

        is_detected, detected_img = self.detect_moving(bg_img, filtered_img, ori_img)
        if is_detected is False:
            if self.prior_detected is True:
                self.counter -= 1
            else:
                self.fps = 1
                return
        else:
            if self.prior_detected is False:
                self.prior_detected = True
                self.counter -= 1
            else:
                self.counter -= 1

        # 움직임이 검출된 경우 이 아래부분에 도달한다
        x, y = self.text_pos
        # 저장하는 프레임의 상한을 저장한다
        if len(self.frames) <= 1000:
            self.frames.append(ori_img)

        buf = detected_img.tostring()
        img_texture = Texture.create(size=(640, 480), colorfmt='bgr')
        img_texture.blit_buffer(buf, colorfmt='bgr')
        self.texture = img_texture

        if self.present_status is False:
            self.present_status = True
            self.add_widget(self.status_label)

        if self.counter <= 0:
            self.counter = 150

            video_path = self.save_video(self.frames)
            is_uploaded = self.upload_video(video_path)

            if is_uploaded is True:
                print 'upload success'
            else:
                print 'upload fail'

            self.prior_detected = False
            self.frames = list()

            # remove status label from view
            self.remove_widget(self.status_label)
            self.present_status = False


class NavWindow(GridLayout):
    def __self__(self, **kwargs):
        super(GridLayout, NavWindow).__init__(**kwargs)
        self.add_widget(Button(text='View Detected Videos'))
        self.add_widget(Button(text='Monitoring Start'))


class MainApp(App):
    def __init__(self, **kwargs):
        super(MainApp, self).__init__(**kwargs)
        self.capture = cv2.VideoCapture(0)
        self.monitoring = MonitoringWindow(self.capture, 24, **kwargs)

    def on_stop(self):
        self.capture.release()

    def build(self):
        return self.monitoring


if __name__ == '__main__':
    MainApp().run()
