from bluepy import btle
from bluepy.btle import DefaultDelegate
import time
import binascii
import collections
import psycopg2
import datetime
import os
import sys


# BMS bluetooth addresses and their indexes
bms_bt_addresses = ["A4:C1:38:E5:BC:FC"]
post2db = False

class BATTERY:
	Total_voltage = 0
	Current_charge = 0
	Current_discharge = 0
	Remaining_capacity = 0
	Typical_capacity = 0
	Cycles = 0
	Balance = 0
	Protection = 0
	cell_v = 0
	cell_b = 0

	def __init__(self):
		self.cell_v = [0,0,0,0,0,0,0,0,0,0,0,0,0,0]
		self.cell_b = [0,0,0,0,0,0,0,0,0,0,0,0,0,0]

	def DecodeMsg03( self, data ):
		self.Total_voltage = int.from_bytes(data[4:6], byteorder='big')/100.0
		c = int.from_bytes(data[6:8], byteorder='big', signed=True)/100.0
		if c>=0:
			self.Current_charge = c;
			self.Current_discharge = 0;
		else:
			self.Current_charge = 0;
			self.Current_discharge = c;

		self.Remaining_capacity = int.from_bytes(data[8:10], byteorder='big', signed=True)/100.0
		self.Typical_capacity = int.from_bytes(data[10:12], byteorder='big', signed=True)/100.0
		self.Cycles = int.from_bytes(data[12:14], byteorder='big', signed=True)
		self.Balance = int.from_bytes(data[16:18], byteorder='big', signed=False)

		#print( data[16:18] );
		#print( self.Balance );

		self.Protection = int.from_bytes(data[20:22], byteorder='big')

	def DecodeMsg04( self, data ):
		for i in range(0,14):
			self.cell_v[i] =  int.from_bytes(data[(4+i*2):(6+i*2)], byteorder='big')/1000.0

	def Output(self):
		print("Total voltage: ", self.Total_voltage, "v     ", end="", sep="")
		print("Ch/DCh: ", round(self.Current_charge,2) , "A / ", round(-self.Current_discharge,2) , "A", sep="")
		print("Capacity: ", self.Remaining_capacity , "Ah / ", self.Typical_capacity, "Ah   (", self.Cycles, " cycles)" )

		print("              ", end='' )
		for i in range(0,14):
			print( '{:5} '.format(i+1), end='' )
		print("")

		print("Cell voltages : ", end='' )
		for i in range(0,14):
			print( '{:5} '.format(self.cell_v[i]), end='' )
		print("")
		print("Status:         ", end='' )
		for i in range(0,14):
			if self.cell_b[i]>0:
				print( "B ", end='')
			else:
				print( "- ", end='')

			if max(self.cell_v) >= min(self.cell_v)+0.020:
				if self.cell_v[i] >= max(self.cell_v)-0.003:
					print( "H   ", end='')
				elif self.cell_v[i] <= min(self.cell_v)+0.003:
					print( "L   ", end='')
				else:
					print( "    ", end='')
			else:
				print( "    ", end='')


		print("")
		print("Protection: ", self.Protection, "   Vmin/max: ", min(self.cell_v),"V / ", max(self.cell_v), "V   diff:", round((max(self.cell_v)-min(self.cell_v))*1000,0), "mV", sep="")


class ReadDelegate(btle.DefaultDelegate):
	data = b''

	def __init__(self):
		btle.DefaultDelegate.__init__(self)

	def handleNotification(self, cHandle, data):
		self.data = self.data + data
		#print(" new data: ", binascii.b2a_hex(data), " complete: ", IsMsgComplete(read_data))
		#print " got data: ", binascii.b2a_hex(data)


class BMS_class:
	bt_dev = 0
	bt_RD = 0
	Battery_id = 0
	Battery = 0
	BatterySamples = 0
	iSamples = 0
	connected = 0
	adr = ""
	id = 0

	def connect(self, tries):
		for tries in range(0,tries):
			try:
				self.bt_dev = btle.Peripheral(self.adr, btle.ADDR_TYPE_PUBLIC, 0)
			except:
				time.sleep(0.5)
				continue
			self.connected = True
			break


	def __init__(self, adr, id):
		self.adr = adr
		self.id = id
		self.connect(5)
		if not self.connected:
			return
	
		self.Battery_id = id
		self.BatterySamples = list()
		self.Battery = BATTERY()
		self.bt_RD = ReadDelegate()
		self.bt_dev.withDelegate( self.bt_RD )

	def CollectSample(self):
		if not self.connected:
			print("Reconnect attempt...", end='' )
			self.connect(1)
			time.sleep(5)
			if not self.connected:
				print("Failed")
				return
			print("OK")

		#print("Services...")
		#for svc in self.bt_dev.services:
		#	print(str(svc))

		#bms_uuid = "0000ff00-0000-1000-8000-00805f9b34fb"
		#service1=self.bt_dev.getServiceByUUID( bms_uuid );

		#print("Characteristics...")
		#for ch in service1.getCharacteristics():
		#	print(str(ch))

		#cha_ff01 = service1.getCharacteristics(0xff01)[0]
		#cha_ff02 = service1.getCharacteristics(0xff02)[0]


		cmd03="DDA50300FFFD77"
		cmd04="DDA50400FFFC77"
		#cmd3="DDA50500FFFB77"

		reply_ok = False
		new_sample = BATTERY();
		for i in range(0,5):
			#print( "Sending command ", cmd03 )
			self.bt_RD.data=b""
			self.bt_dev.writeCharacteristic( 0x000d, bytes.fromhex(cmd03) )
			while self.bt_dev.waitForNotifications(0.2):
				continue
			if IsMsgComplete( self.bt_RD.data, 0x03 ):
				reply_ok = True
				#print(binascii.b2a_hex( self.bt_RD.data ))
				break;

		if reply_ok:
			new_sample.DecodeMsg03( self.bt_RD.data )
			reply_ok = False

			for i in range(0,5):
				#print( "Sending command ", cmd04 )
				self.bt_RD.data=b""
				self.bt_dev.writeCharacteristic( 0x000d, bytes.fromhex(cmd04) )
				while self.bt_dev.waitForNotifications(0.2):
					continue
				if IsMsgComplete( self.bt_RD.data, 0x04 ):
					reply_ok = True
					break;

			if reply_ok:
				#print(binascii.b2a_hex( self.bt_RD.data ))
				new_sample.DecodeMsg04( self.bt_RD.data )
				self.iSamples += 1
				self.BatterySamples.append(new_sample)
				print(".",end='')
				sys.stdout.flush()


	def EvaluateHelper(self,values,sanity_min,sanity_max, precision):
		if not self.connected:
			return
		count = 0
		sum = 0
		for i in range(0,len(values)):
			if sanity_min <= values[i] <= sanity_max:
				sum += values[i]
				count += 1
		if count>0:
			return round(sum/count, precision)
		else:
			return -1

	def Evaluate(self):
		if not self.connected:
			return
		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Total_voltage )
		self.Battery.Total_voltage = self.EvaluateHelper( values, 35,65, 2 );

		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Current_charge )
		self.Battery.Current_charge = self.EvaluateHelper( values, -50,50, 2 );

		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Current_discharge )
		self.Battery.Current_discharge = self.EvaluateHelper( values, -50,50, 2 );

		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Remaining_capacity )
		self.Battery.Remaining_capacity = self.EvaluateHelper( values, 0,250, 2 );

		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Typical_capacity )
		self.Battery.Typical_capacity = self.EvaluateHelper( values, 0,250, 2 );

		for c in range(0,14):
			self.Battery.cell_b[c]=0
			for i in range(0,self.iSamples):
				self.Battery.cell_b[c] += (self.BatterySamples[i].Balance >> c) & 1

		for c in range(0,14):
			values = []
			for i in range(0,self.iSamples):
				values.append( self.BatterySamples[i].cell_v[c] )
			self.Battery.cell_v[c] = self.EvaluateHelper( values, 1,4.3, 3 );

	def Upload(self, pg_cursor, now_time):
		query=( "INSERT INTO battery_minute_data (time, battery_id, voltage, current_charge, current_discharge, remaining_capacity, " +
							"cell01_v, cell02_v, cell03_v, cell04_v, cell05_v, cell06_v, cell07_v, " +
							"cell08_v, cell09_v, cell10_v, cell11_v, cell12_v, cell13_v, cell14_v, " +
							"cell01_b, cell02_b, cell03_b, cell04_b, cell05_b, cell06_b, cell07_b, " +
							"cell08_b, cell09_b, cell10_b, cell11_b, cell12_b, cell13_b, cell14_b ) VALUES ( " +
							"\'"+now_time.strftime("%Y-%m-%d %H:%M")+"\', " +
							str(self.Battery_id) + ", " +
							str(self.Battery.Total_voltage*1000) + ", " +
							str(self.Battery.Current_charge*1000) + ", " +
							str(self.Battery.Current_discharge*1000) + ", " +
							str(self.Battery.Remaining_capacity*1000) + ", " +
							str(self.Battery.cell_v[0]*1000) + ", " +
							str(self.Battery.cell_v[1]*1000) + ", " +
							str(self.Battery.cell_v[2]*1000) + ", " +
							str(self.Battery.cell_v[3]*1000) + ", " +
							str(self.Battery.cell_v[4]*1000) + ", " +
							str(self.Battery.cell_v[5]*1000) + ", " +
							str(self.Battery.cell_v[6]*1000) + ", " +
							str(self.Battery.cell_v[7]*1000) + ", " +
							str(self.Battery.cell_v[8]*1000) + ", " +
							str(self.Battery.cell_v[9]*1000) + ", " +
							str(self.Battery.cell_v[10]*1000) + ", " +
							str(self.Battery.cell_v[11]*1000) + ", " +
							str(self.Battery.cell_v[12]*1000) + ", " +
							str(self.Battery.cell_v[13]*1000) + ", " +
							str(self.Battery.cell_b[0]) + ", " +
							str(self.Battery.cell_b[1]) + ", " +
							str(self.Battery.cell_b[2]) + ", " +
							str(self.Battery.cell_b[3]) + ", " +
							str(self.Battery.cell_b[4]) + ", " +
							str(self.Battery.cell_b[5]) + ", " +
							str(self.Battery.cell_b[6]) + ", " +
							str(self.Battery.cell_b[7]) + ", " +
							str(self.Battery.cell_b[8]) + ", " +
							str(self.Battery.cell_b[9]) + ", " +
							str(self.Battery.cell_b[10]) + ", " +
							str(self.Battery.cell_b[11]) + ", " +
							str(self.Battery.cell_b[12]) + ", " +
							str(self.Battery.cell_b[13]) + " )" )
		pg_cursor.execute(query)


	def __del__(self):
		if not self.connected:
			return
		print( "Disconnecting..." )
		self.bt_dev.disconnect()


def IsMsgComplete( data, cmd ):
	if len(data)<6:   # impossibly short
		 return False
	if data[1] != cmd:   # reply to wrong command
		return False
	if data[3]+7 != len(data):  # length mismatch
		return False
	if data[0] != 0xdd or data[-1]!=0x77:  # no start / end byte
		return False
	if data[2] != 0:  # not a "OK" response
		return False

	checksum=0;
	for i in range(2,data[3]+4):
		checksum = checksum + data[i]
	checksum = (checksum^0xffff)+1
	if ( data[-3] != checksum>>8 ) or ( data[-2] != checksum&0xff ):
		return False

	return True


while True:
	print("Connecting...")

	BMSs = []
	# loop through the defined bms bt addresses and initialize their classes
	ind = 1
	for bt_add in bms_bt_addresses:
		bms_c = BMS_class(bt_add, 1)
		BMSs.append(bms_c)

	start_time = datetime.datetime.now()

	print("Collecting samples...")
	while True:
		time.sleep(10)
		for BMS in BMSs:
			try:
				BMS.CollectSample()
			except (btle.BTLEException,btle.BTLEDisconnectError):
				#os.system("sudo systemctl stop bluetooth")
				#os.system("sudo systemctl start bluetooth")

				print("Bluetooth disconnect error.  Resetting.")

				os.system("sudo hciconfig hci0 reset")
				time.sleep(10)

				BMS = BMS_class(BMS.adr,BMS.id)   # try reconnect
				print("Reconnecting BMS#"+str(BMS.id) )
				continue

		now_time = datetime.datetime.now()
		sample_duration = datetime.timedelta(minutes=5)
		#elapsed_time = now_time - start_time

		# on every 5th minute, but minimum 1 minute elapsed
#		if now_time.minute % 5 == 0 and now_time.minute > start_time.minute+2:
		#if now_time.minute >= start_time.minute+5:
		if now_time >= (start_time + sample_duration):
			break;
	print("")

	if post2db:
		pg = psycopg2.connect( database="grafana2", user="pi", password="raspberry", host="localhost")
		pg_cursor = pg.cursor()

	for BMS in BMSs:
		BMS.Evaluate()

		if BMS.connected and BMS.iSamples>0:
			print('======== Battery #', BMS.id, " ========", sep="")
			BMS.Battery.Output()
			if post2db: BMS.Upload(pg_cursor, now_time)
		del BMS

	del BMSs

	if post2db:
		query=( "INSERT INTO battery_minute_data (time, battery_id, voltage, current_charge, current_discharge, remaining_capacity) " +
				"SELECT time, 0, AVG(voltage), SUM(current_charge), SUM(current_discharge), SUM(remaining_capacity) FROM battery_minute_data " +
				"WHERE time=\'"+now_time.strftime("%Y-%m-%d %H:%M") + "\' GROUP BY 1")
		pg_cursor.execute(query)

		pg.commit()
		pg.close

	os.system("sudo hciconfig hci0 reset")
	print("sleep")
	time.sleep(10)
