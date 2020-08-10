from bluepy import btle
from bluepy.btle import DefaultDelegate
import time
import binascii
import collections
import psycopg2
import datetime
import os
import sys
import re


# BMS bluetooth addresses and their indexes
bms_bt_addresses = [{'name': '7s10p', 'addr': 'A4:C1:38:E5:BC:FC'}]
post2db = False
cells_in_series = 7
sleep_time_between_connection_attempts = 3		# in seconds


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
		self.cell_v = [0 for a in range(cells_in_series)]
		self.cell_b = [0 for a in range(cells_in_series)]

	def DecodeMsg03( self, data ):
		print("Battery stats")
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

		print(
			"Decoded Message:\n\tBattery capacity: %f\n\tTotal Voltage: %fV\n\tCurrent charge = %f\n\tCurrent discharge = %f\n\tRemaining capacity = %f\n\tCycles = %d\n\tBalance: %f\n" % (
				self.Typical_capacity,
				self.Total_voltage,
				self.Current_charge,
				self.Current_discharge,
				self.Remaining_capacity,
				self.Cycles,
				self.Balance
			)
		)

		self.Protection = int.from_bytes(data[20:22], byteorder='big')

	def DecodeMsg04( self, data ):
		print("Cell voltages")
		# print(data)
		for i in range(0, cells_in_series):
			self.cell_v[i] =  int.from_bytes(data[(4+i*2):(6+i*2)], byteorder='big')/1000.0
			print("Cell%d = %fV" % (i, self.cell_v[i]))

	def Output(self):
		print("Total voltage: ", self.Total_voltage, "v     ", end="", sep="")
		print("Ch/DCh: ", round(self.Current_charge,2) , "A / ", round(-self.Current_discharge,2) , "A", sep="")
		print("Capacity: ", self.Remaining_capacity , "Ah / ", self.Typical_capacity, "Ah   (", self.Cycles, " cycles)" )

		print("              ", end='' )
		for i in range(0, cells_in_series):
			print( '{:5} '.format(i+1), end='' )
		print("")

		print("Cell voltages : ", end='' )
		for i in range(0, cells_in_series):
			print( '{:5} '.format(self.cell_v[i]), end='' )
		print("")
		print("Status:         ", end='' )
		for i in range(0, cells_in_series):
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
		# print(data)
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
	writable_characteristics = []
	data_characteristic = None
	cmd03="DDA50300FFFD77"
	cmd04="DDA50400FFFC77"
	# cmd3="DDA50500FFFB77"

	def connect(self, tries):
		for tries in range(0,tries):
			try:
				self.bt_dev = btle.Peripheral(self.adr, btle.ADDR_TYPE_PUBLIC, 0)
				
				# loop through the characteristics and test the writable ones
				for svc in self.bt_dev.getServices():
					# get the characteristics of this services
					all_characteristics = svc.getCharacteristics()
					
					for characteristic in all_characteristics:
						if re.search('WRITE', characteristic.propertiesToString()):
							self.writable_characteristics.append(characteristic.getHandle())

			except Exception as e:
				print(str(e))
				time.sleep(0.5)
				continue
			self.connected = True
			break


	def __init__(self, adr, id, name=None):
		self.adr = adr
		self.id = id
		print("Try and connect to the BMS. Try 5 times")
		self.connect(5)
		if not self.connected:
			print("Couldn't connect to %s the BMS even after trying 5 times" % name if name else '')
			return
		print("Connected to '%s'" % name if name else '')

		self.Battery_id = id
		self.BatterySamples = list()
		self.Battery = BATTERY()
		self.bt_RD = ReadDelegate()
		self.bt_dev.withDelegate( self.bt_RD )


	def determine_data_characteristic(self):
		# determines the characteristic handle which we shall use to query the data from
		for handle_id in self.writable_characteristics:
			try:
				# set the wait for a confirm notification that the write was successful 
				self.bt_dev.writeCharacteristic(handle_id, bytes.fromhex(self.cmd03), True)
				
				# now save this handle and break from the loop
				self.data_characteristic = handle_id
				break
			except Exception as e:
				print(str(e))
				continue


	def CollectSample(self):
		if not self.connected:
			print("Reconnect attempt...", end='' )
			self.connect(1)
			time.sleep(5)
			if not self.connected:
				print("Failed")
				return
			# print("OK")


		cmd03="DDA50300FFFD77"
		cmd04="DDA50400FFFC77"
		#cmd3="DDA50500FFFB77"

		reply_ok = False
		new_sample = BATTERY();
		for i in range(0,5):
			print( "Sending command3 ", self.cmd03 )
			# print(bytes.fromhex(cmd03))
			self.bt_RD.data=b""
			self.bt_dev.writeCharacteristic( self.data_characteristic, bytes.fromhex(self.cmd03), True )
			while self.bt_dev.waitForNotifications(0.2):
				# print("waiting...")
				continue
			
			if IsMsgComplete( self.bt_RD.data, 0x03 ):
				reply_ok = True
				print(binascii.b2a_hex( self.bt_RD.data ))
				break;

		if reply_ok:
			# print("The reply is ok")
			new_sample.DecodeMsg03( self.bt_RD.data )
			reply_ok = False

			for i in range(0,5):
				print( "Sending command4 ", cmd04 )
				self.bt_RD.data=b""
				self.bt_dev.writeCharacteristic( self.data_characteristic, bytes.fromhex(cmd04), True )
				# self.bt_dev.writeCharacteristic( 0x000d, bytes.fromhex(cmd04) )
				while self.bt_dev.waitForNotifications(10):
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
				# sys.stdout.flush()

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

		for c in range(0, cells_in_series):
			self.Battery.cell_b[c]=0
			for i in range(0,self.iSamples):
				self.Battery.cell_b[c] += (self.BatterySamples[i].Balance >> c) & 1

		for c in range(0, cells_in_series):
			values = []
			for i in range(0,self.iSamples):
				values.append( self.BatterySamples[i].cell_v[c] )
			self.Battery.cell_v[c] = self.EvaluateHelper( values, 1,4.3, 3 );

	def Upload(self, pg_cursor, now_time):
		cell_b = []
		cell_v = []
		col_names = ["cell%d" % i for i in range(cells_in_series)]
		for i in range(cells_in_series): cell_v.append(str(self.Battery.cell_v[i]*1000))
		for i in range(cells_in_series): cell_b.append(str(self.Battery.cell_b[i]*1000))

		if post2db:
			query=("INSERT INTO battery_minute_data (time, battery_id, voltage, current_charge, current_discharge, remaining_capacity, %s ) " +
					"VALUES ( " % ', '.join(col_names) +
					"\'"+now_time.strftime("%Y-%m-%d %H:%M")+"\', " +
					str(self.Battery_id) + ", " +
					str(self.Battery.Total_voltage*1000) + ", " +
					str(self.Battery.Current_charge*1000) + ", " +
					str(self.Battery.Current_discharge*1000) + ", " +
					str(self.Battery.Remaining_capacity*1000) + ", %s, %s" % (', '.join(cell_v), ', '.join(cell_b))
			)
			pg_cursor.execute(query)
		else:
			cell_data = (
				now_time.strftime("%Y-%m-%d %H:%M"),
				str(self.Battery_id),
				str(self.Battery.Total_voltage*1000),
				str(self.Battery.Current_charge*1000),
				str(self.Battery.Current_discharge*1000),
				str(self.Battery.Remaining_capacity*1000)
			)
			print(cell_data)
			print(cell_v)
			print("%s Bat: %s, V: %s, Charge: %s, Discharge: %s, Rem Cap: %s" % (cell_data) )
			print("cell1    cell2    cell3    cell4    cell5    cell6    cell7")
			print(cell_v)


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


class BMSDevice:
	def __init__(self, adr, id_, name):
		self.adr = adr
		self.id = id_
		self.name = name
		self.connected = False
		self.writable_characteristics = []
		self.data_characteristic = None
		self.cmd03 = "DDA50300FFFD77"
		self.cmd04="DDA50400FFFC77"
		# self.cmd3="DDA50500FFFB77"
		
	def connect(self, tries):
		for tries in range(0, tries):
			try:
				# create the top level peripheral for this device
				self.bt_dev = btle.Peripheral(self.adr, btle.ADDR_TYPE_PUBLIC, 0)
				
				# loop through the characteristics and test the writable ones
				for svc in self.bt_dev.getServices():
					# get the characteristics of this services
					all_characteristics = svc.getCharacteristics()
					
					for characteristic in all_characteristics:
						if re.search('WRITE', characteristic.propertiesToString()):
							self.writable_characteristics.append(characteristic.getHandle())

				# all is good, so alter the connected flag and exit the loop
				self.connected = True
				break
			except btle.BTLEDisconnectError as e:
				print("Bluetooth connect error.  Resetting.")
				os.system("sudo hciconfig hci0 reset")
				time.sleep(10)
				continue
			except Exception as e:
				print("Some error %s: '%s'\n\tSleeping for %d seconds before retrying " % (self.name, str(e), sleep_time_between_connection_attempts))
				time.sleep(sleep_time_between_connection_attempts)
				continue



while True:
	print("Connecting...")

	BMSs = []
	# loop through the defined bms bt addresses and initialize their classes
	ind = 1
	for bt in bms_bt_addresses:
		bms_c = BMS_class(bt['addr'], 1, bt['name'])
		BMSs.append(bms_c)

	start_time = datetime.datetime.now()

	print("Collecting samples...")
	while True:
		time.sleep(3)
		for BMS in BMSs:
			try:
				if BMS.data_characteristic is None:
					BMS.determine_data_characteristic()

				BMS.CollectSample()
			except btle.BTLEDisconnectError as e:
				#os.system("sudo systemctl stop bluetooth")
				#os.system("sudo systemctl start bluetooth")
				print(str(e))

				print("Bluetooth disconnect error.  Resetting.")

				os.system("sudo hciconfig hci0 reset")
				time.sleep(10)

				BMS = BMS_class(BMS.adr,BMS.id)   # try reconnect
				print("Reconnecting BMS#"+str(BMS.id) )
				continue
			except Exception as e:
				print(str(e))

		now_time = datetime.datetime.now()
		sample_duration = datetime.timedelta(minutes=0.5)
		#elapsed_time = now_time - start_time

		# on every 5th minute, but minimum 1 minute elapsed
#		if now_time.minute % 5 == 0 and now_time.minute > start_time.minute+2:
		#if now_time.minute >= start_time.minute+5:
		if now_time >= (start_time + sample_duration):
			break;
	print("")

	pg_cursor = None
	if post2db:
		pg = psycopg2.connect( database="grafana2", user="pi", password="raspberry", host="localhost")
		pg_cursor = pg.cursor()

	for BMS in BMSs:
		BMS.Evaluate()

		if BMS.connected and BMS.iSamples>0:
			print('======== Battery #', BMS.id, " ========", sep="")
			BMS.Battery.Output()
			BMS.Upload(pg_cursor, now_time)
		del BMS

	del BMSs

	query=( "INSERT INTO battery_minute_data (time, battery_id, voltage, current_charge, current_discharge, remaining_capacity) " +
			"SELECT time, 0, AVG(voltage), SUM(current_charge), SUM(current_discharge), SUM(remaining_capacity) FROM battery_minute_data " +
			"WHERE time=\'"+now_time.strftime("%Y-%m-%d %H:%M") + "\' GROUP BY 1")

	if post2db:
		pg_cursor.execute(query)

		pg.commit()
		pg.close
	else:
		# print(query)
		print('')

	os.system("sudo hciconfig hci0 reset")
	print("sleep")
	time.sleep(10)
