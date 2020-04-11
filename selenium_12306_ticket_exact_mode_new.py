#! /usr/bin/env
# -*- coding:utf-8 -*-

import requests
import json
import time
import datetime
from selenium import webdriver
from selenium.common.exceptions import TimeoutException,NoSuchElementException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support.select import Select
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support import expected_conditions as EC
from chaojiying import chaojiying  # 第三方工具超级鹰的调用代码
from PIL import Image  # 对于后续对验证码图片需要进行保存读取的操作
import os
import re
import getpass

code_login = False #True扫码  False账号密码
time_out = 60
poll_frequency = 0.1
requery = True

seat_no = {
    '商务座':1,
    '一等座':2,
    '二等座':3,
    '高级软卧':4,
    '软卧':5,
    '动卧':6,
    '硬卧':7,
    '软座':8,
    '硬座':9,
    '无座':10
}

def print_t(*content):
    print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time())),*content)

def get_citylist_from_12306():
    dict_city = {}
    s_list = re.findall('var station_names =\'(.*?)\';', requests.get('https://kyfw.12306.cn/otn/resources/js/framework/station_name.js').text)[0].split('@')
    for s in s_list:
        if '' == s:
            continue
        l_list = s.split('|')
        dict_city[l_list[1]] = l_list[2]

    return dict_city

# 下载所有的车次数据  保存为 train_list.txt文件
def get_train_list():
    requests.adapters.DEFAULT_RETRIES = 5
    response = requests.get('https://kyfw.12306.cn/otn/resources/js/query//train_list.js?scriptVersion=1.0', stream=True, verify=False)
    status = response.status_code
    if status == 200:
        with open('./config/train_list.txt', 'wb') as of:
            for chunk in response.iter_content(chunk_size=102400):
                if chunk:
                    of.write(chunk)

def get_train_no(train_code):
    c = list(train_code)[0]
    with open('./config/train_list.txt', 'rb') as of:
        text = of.readline()
        tt = text.decode("utf-8")
        ss = tt.replace('var train_list =','').replace("},{", "},\n{")

        d = json.loads(ss)
        date = '2019-07-16'
        for k in d[date][c]:
            if k['station_train_code'].find(train_code+'(')>-1:
                return k['train_no']

def wait_loading_or_exit(driver,xpath,msg='等待加载完成'):
    try:
        print_t(msg)
        WebDriverWait(driver, time_out, poll_frequency).until(
            lambda x: x.find_element_by_xpath(xpath).is_displayed())
    except Exception as e:
        if isinstance(e,TimeoutException):
            print_t('网络超时，即将退出,请确认网络后发起重试')
        else:
            print_t(e)
        driver.close()
        exit(1)

def click_query_ticket(driver):
    try:
        driver.find_element_by_xpath('//a[@id="query_ticket"]').click()
    except Exception as e:
        if not check_query_ticket_success(driver):
            time.sleep(1)
            click_query_ticket(driver)


    print_t('点击查询按钮并且等待恢复可点击状态(等待查询完成)')
    try:
        WebDriverWait(driver, 60, 0.1).until(
            lambda x: x.find_element_by_xpath('//a[@id="query_ticket"]').is_enabled())
    except Exception as e:
        if isinstance(e, TimeoutException):
            print_t('网络超时，即将退出,请确认网络后发起重试')
        else:
            print(e)
        driver.close()
        exit(1)

    time.sleep(1)

def check_query_ticket_success(driver):
    try:
        EC.visibility_of_element_located(driver.find_element_by_xpath('//div[@class="sear-result"]'))
        print_t('车票信息查询成功')
        return True
    except Exception as e:
        print(e)

    try:
        EC.visibility_of_element_located(driver.find_element_by_xpath('//div[@class="no-ticket"]'))
        print_t('车票信息查询失败')
        return False
    except Exception as e:
        print(e)
    return False

def query_ticket_or_requery(driver):
    global requery
    click_query_ticket(driver)

    while not check_query_ticket_success(driver):
        click_query_ticket(driver)

    TRAIN_NO_TAIL=['00','01','02','03','04','05','06','07','08','09','0A','0B','0C','0D','0F']
    findTrainNo = False
    for tail in TRAIN_NO_TAIL:
        if findTrainNo:#已经找到了，退出循环
            break
        trainNo = train_no[:-2]+tail
        try:
            tr = driver.find_element_by_id("ticket_"+trainNo)
            print_t("找到车次: " + trainNo)
            row_list =[td.text for td in tr.find_elements_by_xpath('./td')]
            print_t(row_list)
            if len(row_list) > 0:
                train_code = row_list[0].split('\n')[0]
                print_t(train_code)
                if train_code == ticket_12306_config_dict['train_code']:
                    for seat in ticket_12306_config_dict['train_seat']:
                        print_t(seat)
                        if has_seat(row_list, seat_no[seat]):
                            requery = False

                            tr.find_element_by_xpath('./td/a').click()
                            print_t("查票成功跳转到购买页")
                            findTrainNo = True
                            break
        except Exception as e:
            if isinstance(e,NoSuchElementException):
                print_t("没有找到 "+trainNo)
                # print_t("没有找到该车次，可能该车次已经停售，系统将继续尝试，你可以Ctrl C退出选择其他车次")

    if requery:
        print_t('没有票，将再次发起查询')
        query_ticket_or_requery(driver)

def has_seat(row_list,no):
    return row_list[no] == '有' or isinstance(int(row_list[no]),int)


def get_right_train(buy_train_code,ticket_12306_config_dict):
    for priority in ticket_12306_config_dict['priority_train']:
        if priority['train_code'] == buy_train_code :
            return priority

# 图形验证码
def code_distinguish(browser):
    # 拿到验证码图片的节点定位
    code_img = browser.find_element_by_css_selector('#J-loginImg')
    # 2.1这里的location是获取这张图片的左上角的左边，返回的是字典封装的x,y的值.基于整个网页返回给你的值
    loca = code_img.location  # x,y{'x': 856, 'y': 284}
    # 1.所以，一般还需要拿到这张图片的尺寸，即长和宽
    size = code_img.size  # {'height': 188, 'width': 300}
    # 2.2接下来，就是需要做截屏。
    # 1.需要定位左上角和右下角2个点的左边，即共4个.保存在元祖中
    code_position = (int(loca['x']), int(loca['y']), int(loca['x'] + size['width']), int(loca['y'] + size['height']))
    # 2.调用截图功能，将图片截取下去。这个功能在无头浏览器中应用的比较多，比如你想验证无头浏览器是否访问到了你想要的页面，就可以使用截图来测试观看
    # 3.截取当前浏览器打开的这张页面的整个图像（记住，是整个浏览器打开的页面的图像）
    browser.save_screenshot('./pic/aa.png')
    # 4.用Image包打开这张截图
    i = Image.open('pic/aa.png')
    # 5.给要截取的验证码图片取名
    code_img_name = './pic/code.png'
    # 6.调用crop函数，在这大的图片里面通过2个点对其内部的内容进行截图
    frame = i.crop(code_position)
    # 7.将截取下来的图片存到目录中，并取名
    frame.save(code_img_name)

    # 2.3调用超级鹰进行识别，拿到返回的结果
    im = open('pic/code.png', 'rb').read()
    # {'err_no': 0, 'err_str': 'OK', 'pic_id': '3095313233818200001', 'pic_str': '25,143|260,134', 'md5': '29c583678bdf3eb09ece5726fcfaa285'}
    result = chaojiying.PostPic(im, 9004)
    print(result)
    coords = result['pic_str']
    chaojiying.ReportError(result['pic_id'])
    # 1.解析超级鹰返回的数据
    # 先声明一个数组用来存储所有的图片坐标,想要的是这种结果[[25,143],[260,134]]
    all_list = []
    if '|' in coords:
        list1 = coords.split('|')  # -->['25,143', '260,134']
        count_list = len(list1)
        for i in range(count_list):
            xy = []
            x = int(list1[i].split(',')[0])
            y = int(list1[i].split(',')[1])
            xy.append(x)
            xy.append(y)
            all_list.append(xy)
        # 针对的是只有一组图片符合的数据['25,143']
    else:
        xy = []
        x = int(coords.split(',')[0])
        y = int(coords.split(',')[1])
        xy.append(x)
        xy.append(y)
        all_list.append(xy)
    # 2.4拿到返回结果后，需要调用动作链，以此点击选中的图片坐标.
    action = ActionChains(browser)
    for i in all_list:
        x = i[0]
        y = i[1]
        # 2.4.1:这样使用move_to_element_with_offset。表示选中一个区域再进行移动。因为返回的坐标数值是以发送的图片作为参照，而我们需要进行点击是要在整张页面中。为了解决这个问题，需要把范围先切换到页面中的图片上
        print('鼠标移动到图片的相对坐标，x:',x,', y:',y)
        ActionChains(browser).move_to_element_with_offset(code_img, x, y).click().perform()
    time.sleep(1)

def login(driver):
    username = input("Please input your username:")
    password = getpass.getpass("Please input your password:")

    if not username or not password:
        print_t("用户名或密码为空")
        exit(1)

    # 点击进行账号密码登陆
    driver.find_element_by_css_selector('body > div.login-panel > div.login-box > ul > li.login-hd-account > a').click()
    time.sleep(1)
    # 进行图片选择
    code_distinguish(driver)

    print_t('开始自动填充用户名密码')

    driver.find_element_by_xpath('//input[@id="J-userName"]').clear()
    # driver.find_element_by_xpath('//input[@id="J-userName"]').send_keys(ticket_12306_config_dict['username'])  # 填充用户名
    driver.find_element_by_xpath('//input[@id="J-userName"]').send_keys(username)  # 填充用户名

    driver.find_element_by_xpath('//input[@id="J-password"]').clear()
    # driver.find_element_by_xpath('//input[@id="J-password"]').send_keys(ticket_12306_config_dict['password'])  # 填充用户名
    driver.find_element_by_xpath('//input[@id="J-password"]').send_keys(password)  # 填充用户名

    time.sleep(1)
    driver.find_element_by_css_selector('#J-login').click()
    try:
        WebDriverWait(driver, 3, poll_frequency).until(
            lambda x: x.find_element_by_xpath('//div[@class="modal-ft"]').is_displayed())
    except Exception as e:
        print('密码错误或验证码有误，重试~~~~')
        login(driver)


if __name__ == '__main__':
    print_t('开始读取配置文件')
    try:
        with open('./config/ticket_12306_exact_mode_config.json','r') as f:
            ticket_12306_config = f.read()
    except FileNotFoundError as e:
        print_t('没有找到配置文件，系统已退出，请先下载配置文件ticket_12306_config.json到当前运行环境目录下的config目录')
        exit(1)

    ticket_12306_config_dict = json.loads(ticket_12306_config)
    print_t('配置文件读取成功')

    print_t('开始加载全部城市列表')
    try:
        with open('./config/ticket_12306_citylist.json','r') as f:
            ticket_12306_citylist = f.read()
            ticket_12306_citylist_dict = json.loads(ticket_12306_citylist)
    except FileNotFoundError as e:
        print_t('没有找到全部城市列表文件，系统将从网络下载，为提高速度请先下载全部城市列表ticket_12306_citylist.json到当前运行环境目录下的config目录')
        try:
            ticket_12306_citylist_dict = get_citylist_from_12306()
        except Exception as e2:
            print_t('系统从网络下载全部城市列表失败，系统将退出')
            exit(1)

    print_t('全部城市列表读取成功')

    if ticket_12306_citylist_dict.get(ticket_12306_config_dict['from_station_text'],'') == ''\
            or ticket_12306_citylist_dict.get(ticket_12306_config_dict['to_station_text'],'') == '':
        print_t('请填写正确的车次信息')
        exit(1)

    ticket_12306_config_dict['from_station'] = ticket_12306_citylist_dict[ticket_12306_config_dict['from_station_text']]
    ticket_12306_config_dict['to_station'] = ticket_12306_citylist_dict[ticket_12306_config_dict['to_station_text']]

    try:
        datetime.datetime.strptime(re.findall('\'(.*?)\'', ticket_12306_config_dict['travel_date'])[0], '%Y-%m-%d')
    except ValueError as e:
        print_t('请填写正确的出发时间信息')
        exit(1)

    if not os.path.exists("./config/train_list.txt"):
        print_t('开始下载当前12306全部车次信息，50M左右，下载时间比较长，请耐心等待')
        get_train_list()
        print_t('下载当前12306全部车次信息，50M左右，下载完成')

    train_no = get_train_no(ticket_12306_config_dict['train_code'])
    if not train_no:
        print_t('你当前要购买的车次不存在，无法购买，系统将退出')


    print_t('系统配置读取完成')
    print('   您将为',ticket_12306_config_dict['passenger_list'],'购买在',\
            ticket_12306_config_dict['travel_date'],'由',ticket_12306_config_dict['from_station_text'],\
            '开往', ticket_12306_config_dict['to_station_text'],'的列车')
    print('   系统将选择',ticket_12306_config_dict['train_code'],'列车的',ticket_12306_config_dict['train_seat'],'席位')


    print_t('准备完成即将开始购票')

    driver = webdriver.Chrome('/usr/local/Caskroom/chromedriver/80.0.3987.106/chromedriver')
    driver.maximize_window()
    print_t('开始进入登录页面')
    driver.get('https://kyfw.12306.cn/otn/resources/login.html')

    wait_loading_or_exit(driver,'//div[@class="login-code"]/div[@class="login-code-con"]/div[@class="login-code-main"]/div[@class="code-pic"]/img[@id="J-qrImg"]','等待扫码登录登录码加载完成')

    print_t('系统目前启用扫码登录，请打开手机12306客户端完成扫码登录，启用账户密码的方式为修改为 code_login 为 False')
    if not code_login:
        login(driver)

    # 自动点击提示框的 "确认"按钮
    wait_loading_or_exit(driver,'//div[@class="modal-ft"]', '等待提示框的出现')
    driver.find_element_by_css_selector('.ok').click()

    wait_loading_or_exit(driver, '//li[@id="J-header-logout"]', '等待登录完成')

    wait_loading_or_exit(driver, '//li[@id="J-chepiao"]/a', '等待车票按钮显示完成')

    print_t('自动将鼠标放到车票按钮上')
    ActionChains(driver).move_to_element(driver.find_element_by_xpath('//li[@id="J-chepiao"]/a')).perform()

    wait_loading_or_exit(driver, '//div[@class="nav-bd-item nav-col2"]/ul[@class="nav-con"]/li[@class="nav_dan"]/a', '等待单程按钮显示完成')

    print_t('自动点击单程按钮，加载查询车票页')
    driver.find_element_by_xpath('//div[@class="nav-bd-item nav-col2"]/ul[@class="nav-con"]/li[@class="nav_dan"]/a').click()

    wait_loading_or_exit(driver, '//input[@id="fromStationText"]', '等待查询车票页面加载完成')

    print_t('自动填充购票车站信息')
    fromStation = driver.find_element_by_xpath('//input[@id="fromStation"]')
    driver.execute_script('arguments[0].removeAttribute(\"type\")', fromStation)

    driver.find_element_by_xpath('//input[@id="fromStationText"]').clear()
    driver.find_element_by_xpath('//input[@id="fromStationText"]').send_keys(ticket_12306_config_dict['from_station_text'])

    driver.find_element_by_xpath('//input[@id="fromStation"]').clear()
    driver.find_element_by_xpath('//input[@id="fromStation"]').send_keys(ticket_12306_config_dict['from_station'])

    toStation = driver.find_element_by_xpath('//input[@id="toStation"]')
    driver.execute_script('arguments[0].removeAttribute(\"type\")', toStation)

    driver.find_element_by_xpath('//input[@id="toStationText"]').clear()
    driver.find_element_by_xpath('//input[@id="toStationText"]').send_keys(ticket_12306_config_dict['to_station_text'])  # 填充目的地

    driver.find_element_by_xpath('//input[@id="toStation"]').clear()
    driver.find_element_by_xpath('//input[@id="toStation"]').send_keys(ticket_12306_config_dict['to_station'])  # 填充目的地

    js = 'document.getElementById("train_date").removeAttribute("readonly");'
    driver.execute_script(js)
    js_value = 'document.getElementById("train_date").value='+ticket_12306_config_dict['travel_date']
    driver.execute_script(js_value)

    print_t('将开始发起查询')
    query_ticket_or_requery(driver)

    wait_loading_or_exit(driver, '//ul[@id="normal_passenger_id"]', '等待乘车人列表加载完成')

    normal_passenger_li_list = driver.find_elements_by_xpath('//ul[@id="normal_passenger_id"]/li')

    for li in normal_passenger_li_list:
        name_label = li.find_element_by_xpath('./label').text
        for passenger in ticket_12306_config_dict['passenger_list']:
            if name_label.find(passenger) > -1:
                print_t('自动选择乘车人',passenger)
                li.find_element_by_xpath('./input').click()

    buy_train_code = driver.find_element_by_xpath('//p[@id="ticket_tit_id"]/strong[@class="ml5"]').text

    for i,passerger in enumerate(ticket_12306_config_dict['passenger_list']):
        selector = Select(driver.find_element_by_id("seatType_"+str(i+1)))
        select_seat_list = [o.text.replace(' ','').replace('\n','')  for o in selector.options]
        print_t('自动选择座位类型，目前可选择的座位类型有',select_seat_list)

        set_seat_success = False
        for train_seat in ticket_12306_config_dict['train_seat']:
            for i,select_seat in enumerate(select_seat_list):
                if select_seat.find(train_seat)>-1 and not set_seat_success:
                    print_t('为',passerger,'自动选择座位类型，目前为你成功选择座位类型为', train_seat)
                    selector.select_by_index(i)
                    set_seat_success = True
                    break

    time.sleep(1)
    print_t('自动点击提交购票按钮')
    driver.find_element_by_id("submitOrder_id").click()
    time.sleep(1)
    print_t('等待确认购买按钮加载完成')
    try:
        WebDriverWait(driver, 10, 0.1).until(
            lambda x: x.find_element_by_id("qr_submit_id").is_displayed())
    except Exception as e:
        if isinstance(e,TimeoutException):
            print_t('网络超时，即将退出,请确认网络后发起重试')
        else:
            print(e)
        driver.close()
        exit(1)
    time.sleep(2)
    print_t('自动点击确认购买按钮')
    # driver.find_element_by_id("qr_submit_id").click()
    input("完成购买！请在30分钟内登录账户，完成付款,点击Enter退出购票")

    time.sleep(5)
    driver.close()
    exit(1)
