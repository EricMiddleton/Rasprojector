#!/usr/bin/python
from __future__ import absolute_import, division, print_function, unicode_literals

import random, time, glob, threading, imaplib, email, smtplib, os, Image, Queue
import RPi.GPIO as GPIO
from pi3d import Display
from pi3d.Texture import Texture
from pi3d.Shader import Shader
from pi3d.shape.Canvas import Canvas

#This code is designed for a digital photo frame that receives new photos and multimedia snapchats
#sent from a cell phone to an IMAP4 based email account.

phoneTxt = "number@provider.com"									#Your cell's email portal
phoneMMS = "number@provider.com"									#Your cell's MMS email portal
phoneEmail = "mail@gmail.com"					  		#Your smartphone's email address
frameEmail = "mail@gmail.com"							#The IMAP4 email account for the frame
frameEmailPass = "password"										#The email account's password

picFolder = "/home/pi/Frame/pi3d/pics/"								#Folder for pictures

pics = []
nPics = 0
newPics = []
nNewPics = 0
snaps = []
snapType = []
nSnaps = 0
curPic = 0
scrSize = 720, 480
picTime = 5

gThread = None

disp = None
canvas = None

curTex = None
nextTex = None
soundTex = None
curRat = None
nextRat = None

showSnap = 0
curSnap = None
curSnapType = 0

imap = None
smtp = None
receipt = None

q = None

#Init(void)
#Initializes all variables and processes new pictures
def Init():
	global curPic
	global canvas
	global disp
	global soundTex
	global q
	
	#Max out the analog volume
	os.system("amixer cset numid=1 400") 
	
	#Create black display with 2D flat shader and Canvas object
	disp = Display.create(background=(0.0, 0.0, 0.0, 1.0), x=0, y=0)
	shader = Shader("/home/pi/Frame/pi3d/shaders/2d_flat")
	canvas = Canvas()
	canvas.set_shader(shader)
	
	#Queue for gmail thread
	q = Queue.Queue()
	
	InitGmail()
	
	random.seed()
	
	#The image to be displayed whilst a sound is being played
	soundTex = Texture("/home/pi/Frame/pi3d/sound.jpg")
	
	#Init GPIO pins. Buttons on 7 and 8 for shutdown and snapchat functions. Snapchat indicator LED on 25.
	GPIO.setmode(GPIO.BCM)
	GPIO.setup(7, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	GPIO.setup(8, GPIO.IN, pull_up_down=GPIO.PUD_UP)
	GPIO.setup(25, GPIO.OUT, initial=GPIO.LOW)
	
	#Process all unprocessed pics
	ResizePics()
	
	#Load all processed pics
	FindPics()
	
	#Shuffle the list
	Shuffle()
	
	#Load the first, but wait until it's done
	LoadPic(0, True)
	curPic = 1
	
	#Display the loaded pic
	SwapBuffers()

#Draw(t)
#Draws the current texture to the canvas
#t is time, between 0 and 1
#Can be potentially used to create animations and transitions
def Draw(t):
	global canvas
	
	pw = 480*curRat
	ph = 480
	px = (720-pw)/2
	py = 0
	canvas.set_texture(curTex)
	canvas.set_2d_size(w=pw, h=ph, x=px, y=py)
	canvas.draw()

#InitGmail(void)
#Initializes the Gmail Thread
def InitGmail():
	global gThread
	
	gThread = threading.Thread(target=GmailThread)
	gThread.daemon = True
	gThread.start()

#GmailThread(void)
#Seperate thread that communicates with the GMail servers
#It waits until a successful IMAP4 and SMTP connection can be
#made to the server. It then loads all new emails from your
#cell's MMS portal and your phone's email account and downloads
#any multimedia files found
def GmailThread():
	global smtp
	global receipt
	global snaps
	global snapType
	global nSnaps
	global q
	
	running = True
	
	while running:
		try:
			imap = imaplib.IMAP4_SSL('imap.gmail.com')
			imap.login(frameEmail, frameEmailPass)
			
			smtp = smtplib.SMTP('smtp.gmail.com', 587)
			smtp.ehlo()
			smtp.starttls()
			smtp.login(frameEmail, frameEmailPass)
			
			headers = ["from: " + frameEmail,
					"subject: ",
					"to: " + phoneTxt,
					"MIME-Version: 1.0",
					"Content-Type: text/html"]
			
			receipt = "\r\n".join(headers) + "\r\n\r\n"
		except:
			time.sleep(0.5)
			continue
		else:
			break
	
	os.system("sudo ddclient")
	
	try:
		smtp.sendmail(frameEmail, phoneTxt, receipt + "I'm on!")
	except:
		print("Failed to send Email")
	
	searchTerm = 'NOT SEEN OR FROM \"' + phoneMMS + '\" FROM \"' + phoneEmail + '\"'
	
	while 1:
		time.sleep(0.5)
		try:
			imap.select('inbox')
		except:
			print("Unable to open 'inbox'")
			continue
		
		try:
			resp, items = imap.search(None, searchTerm)
		except:
			print("Failed to search for " + searchTerm)
			continue
		
		items = items[0].split()
		
		for emailid in items:
			isSnap = False
			
			try:
				resp, data = imap.fetch(emailid, "(RFC822)")
			except:
				print("Failed to fetch message data")
				continue
			
			mailBody = data[0][1]
			mail = email.message_from_string(mailBody)
			
			if mail.get_content_maintype() != 'multipart':
				continue
			
			received = []
			recNames = []
			recType = []
			
			for part in mail.walk():
				type = part.get_content_maintype()
				if type == 'text':
					text = part.get_payload()
					if text.lower().find("snapchat") != -1:
						isSnap = True
				
				if type == 'video':
					print("New Video!")
					fname = picFolder + part.get_filename()
					received.append(part.get_payload(decode=True))
					recNames.append(fname)
					recType.append(1)
					isSnap = True
				
				elif type == 'audio':
					print("New Audio!")
					fname = picFolder + part.get_filename()
					received.append(part.get_payload(decode=True))
					recNames.append(fname)
					recType.append(2)
					isSnap = True
				
				elif type == 'image':
					print("New Image!")
					fname = picFolder + part.get_filename()
					received.append(part.get_payload(decode=True))
					recNames.append(fname)
					recType.append(0)
			
			for i in range(len(received)):
				fname = recNames[i]
				ftype = recType[i]
				fp = open(fname, 'wb')
				fp.write(received[i])
				fp.close()
				
				if isSnap:
					ProcessSnapchat(fname, ftype)
					
					if ftype == 0:
						response = "Thanks for the Snapchat!"
					elif ftype == 1:
						response = "Thanks for the Snapchat Video!"
					elif ftype == 2:
						response = "Thanks for the Snapchat Sound!"
				
				else:	
					ResizePics([fname])
				
				smtp.sendmail(frameEmail, phoneTxt, receipt + response)
		
		try:
			command = q.get_nowait()
			
			smtp.sendmail(frameEmail, phoneTxt, receipt + response)
			
			if command.find("I'm shutting down") != -1:
				running = False
				q.task_done()
				break
		except:
			time.sleep(0)
		
		time.sleep(0.5)
	
	imap.close()
	imap.logout()
	
	smtp.quit()

#ProcessSnapchat(fname, type)
#Processes new snapchat (fname)
#type defines which type of multimedia the snapchat is:
#0: Image
#1: Video
#2: Sound
def ProcessSnapchat(fname, type):
	global nSnaps
	global snaps
	global snapType
	
	if nSnaps == 0:
		GPIO.output(25, True)
	
	if type == 0:
		fname = ResizePics([fname], False, False)
	
	snaps.append(fname)
	snapType.append(type)
	nSnaps += 1

#ResizePics(fname = None, saveOrig = True, addToList = True)
#Resizes all pics found in list fname, saves the originals if saveOrig is True,
#and adds them to the photo display list if addToList is True.
#If fname is None, it finds all .jpg files in picFolder
def ResizePics(fname = None, saveOrig = True, addToList = True):
	global newPics
	global nNewPics
	global snaps
	global nSnaps
	global snapType
	
	if fname is None:
		pics = glob.glob("/home/pi/Frame/pi3d/pics/*.jpg")
	else:
		pics = fname
	
	for i in range(len(pics)):
		inFile = pics[i]
		fPath, fName = os.path.split(inFile)
		
		outFileLg = fPath + "/original/" + RemoveExt(fName) + "jpg"
		outFileSm = fPath + "/frames/" + RemoveExt(fName) + "jpg"
		
		im = Image.open(inFile)
		if saveOrig is True:
			im.save(outFileLg, "JPEG")
		
		im.thumbnail(scrSize, Image.ANTIALIAS)
		im.save(outFileSm, "JPEG")
		
		os.remove(inFile)
		
		if addToList is True:
			newPics.append(outFileSm)
			nNewPics += 1
		
		return outFileSm

#FindPics(void)
#Loads all resized pics
def FindPics():
	global pics
	global nPics
	
	pics = glob.glob(picFolder + "frames/*.jpg")
	nPics = len(pics)

#Shuffle(wait=True)
#Shuffles the images in a separate thread
#Shuffle will block if wait is True
def Shuffle(wait=True):
	global pics
	
	thr = threading.Thread(target=random.shuffle, args=(pics,))
	thr.daemon = True
	thr.start()
	
	if wait is True:
		thr.join()

#LoadPic(id, wait=False)
#Loads picture from pics at id
#If there are pictures in newPics, it will display the first
#from there instead
#LoadPic will block if wait is true
def LoadPic(id, wait=False):
	global pics
	global nPics
	global newPics
	global nNewPics
	
	if nNewPics > 0:
		fname = newPics[0]
		newPics = newPics[1:]
		nNewPics -= 1
		
		pics.insert(0, fname)
		nPics += 1
	else:
		fname = pics[id]
	
	thr = threading.Thread(target=LoadTexThread, args=(fname,))
	thr.daemon = True
	thr.start()
		
	if wait is True:
		thr.join()

#LoadSnapchat(wait=False)
#Loads the next snapchat
#Sounds and Videos aren't actually loaded
#But pictures are loaded in a seperate thread
#That will block if wait is True
def LoadSnapchat(wait=False):
	global snaps
	global nSnaps
	global showSnap
	global snapType
	global curSnap
	global curSnapType

	if nSnaps <= 0:
		return
	
	if snapType[0] == 0:
		showSnap = 1
		thr = threading.Thread(target=LoadTexThread, args=(snaps[0], True))
		thr.daemon = True
		thr.start()
		
		if wait is True:
			thr.join()
	else:
		showSnap = 2
	
	curSnapType = snapType[0]
	curSnap = snaps[0]
	
	snaps = snaps[1:]
	snapType = snapType[1:]
	nSnaps -= 1
	
	if nSnaps == 0:
		GPIO.output(25, False)
	
	q.put_nowait("I displayed your snapchat!")

#LoadTexThread(fname, snap=False)
#Thread that loads fname into nextTex
#Will delete original image if snap is True
def LoadTexThread(fname, snap=False):
	global nextTex
	global nextRat
	global showSnap
	
	nextTex = Texture(fname)
	nextRat = (nextTex.ix / nextTex.iy) * 0.84375 #correct for screen's aspect ratio
	
	if snap is True:
		os.remove(fname)
		showSnap = 2

#SwapBuffers(void)
#Loads nextTex into curText
def SwapBuffers():
	global curTex
	global curRat

	curTex = nextTex
	curRat = nextRat

#RemoveExt(fname)
#Returns fname without the extension, but with ending period (.)
def RemoveExt(fname):
	i = fname.rfind('.')
	if i == -1:
		return fname + "."
	else:
		return fname[:i+1]

#Close(void)
#Called when GPIO7 is pressed.
#Safely closes GPIO library, Pi3D, and Gmail Thread
def Close():
	global disp
	global smtp
	global receipt
	
	q.put("I'm shutting down")
	gThread.join()
	
	GPIO.cleanup()
	disp.stop()
	
	os.system("sudo shutdown -h now")

Init()

nextTime = time.time() + picTime

while disp.loop_running():
	if GPIO.input(8) == 0 and nSnaps > 0 and showSnap == 0:					#If the button is pressed, there is a snapchat, and there are no snapchats being loaded
		LoadSnapchat()
	
	if time.time() >= nextTime and showSnap != 1:							#If the picture has been up for at least picTime and there are no currently loading snapchats
		if showSnap == 2 and curSnapType != 0:								#If a non-image snapchat is ready
			if curSnapType == 1:
				os.system("omxplayer -o local \"" + curSnap + "\"")			#Play the video through omxplayer and delete it after
				os.remove(curSnap)
			
			elif curSnapType == 2:
				canvas.set_texture(soundTex)								#Display the sound texture
				canvas.set_2d_size(w=720, h=480, x=0, y=0)
				canvas.draw()
				disp.loop_running()
				
				os.system("mplayer \"" + curSnap + "\"")					#Play the sound through mplayer and delete it after
				os.remove(curSnap)
			
		SwapBuffers()														#Flip back buffer to front
		LoadPic(curPic)														#Load next picture
		curPic += 1
		if curPic >= nPics:
			Shuffle()
			curPic = 0			
		
		if showSnap == 2:
			showSnap = 0
		
		nextTime = time.time() + picTime
	
	if GPIO.input(7) == 0:
		Close()
		break
	
	Draw((time.time() - nextTime + picTime)/picTime)
