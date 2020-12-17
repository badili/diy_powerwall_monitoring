from bluepy import btle
from bluepy.btle import DefaultDelegate
import time
import binascii
import collections
import datetime
import os
import sys
import re
import json
import mysql.connector
import paho.mqtt.publish as mqtt
import signal

from raven import Client

import configparser
cfg = configparser.ConfigParser()
cfg.read('pazuri.cfg')

if cfg['SAVE'].getboolean('USE_LOCAL_POSTGRES'):
	import psycopg2

USE_SENTRY = False
ENV_ROLE = cfg['MAIN']['ENV_ROLE']
SAVE_DATA_ONLINE = cfg['SAVE'].getboolean('SAVEDATAONLINE')
SAVE_2_POSTGRES = cfg['SAVE'].getboolean('USE_LOCAL_POSTGRES')
PUBLISH_2_MQTT = cfg['SAVE'].getboolean('PUBLISH_2_MQTT')

if cfg['MAIN'].getboolean('USE_SENTRY'):
	dsn = 'https://%s:%s@%s/%s?verify_ssl=0' % (cfg['SENTRY']['USER'], cfg['SENTRY']['PASS'], cfg['SENTRY']['URL'], cfg['SENTRY']['PROJID'])
	sentry = Client(dsn, environment = cfg['MAIN']['ENV_ROLE'])
	USE_SENTRY = True


class TimeoutException(Exception):
	pass

class BMSConnectionError(Exception):
	pass

class CheckSumError(Exception):
	pass

class BMSReadError(Exception):
	pass

class ReadDelegate(btle.DefaultDelegate):
	data = b''

	def __init__(self):
		btle.DefaultDelegate.__init__(self)

	def handleNotification(self, cHandle, data):
		# print(data)
		self.data = self.data + data
		#print(" new data: ", binascii.b2a_hex(data), " complete: ", IsMsgComplete(read_data))
		#print " got data: ", binascii.b2a_hex(data)


# THIS CLASS WILL BE DEPRECATED!!
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
	batt_time = None
	cell_time = None
	cells_in_series = None

	def __init__(self, cells_in_series):
		self.cells_in_series = cells_in_series
		self.cell_v = [0 for a in range(self.cells_in_series)]
		self.cell_b = [0 for a in range(self.cells_in_series)]

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
		batt_stats_time = datetime.datetime.now()
		self.batt_time = batt_stats_time.strftime("%Y-%m-%d %H:%M:%S")

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
		for i in range(0, self.cells_in_series):
			self.cell_v[i] =  int.from_bytes(data[(4+i*2):(6+i*2)], byteorder='big')/1000.0
			print("Cell%d = %fV" % (i, self.cell_v[i]))

		cells_v_time = datetime.datetime.now()
		self.cells_time = cells_v_time.strftime("%Y-%m-%d %H:%M:%S")

	def Output(self):
		print("Total voltage: ", self.Total_voltage, "v     ", end="", sep="")
		print("Ch/DCh: ", round(self.Current_charge,2) , "A / ", round(-self.Current_discharge,2) , "A", sep="")
		print("Capacity: ", self.Remaining_capacity , "Ah / ", self.Typical_capacity, "Ah   (", self.Cycles, " cycles)" )

		print("              ", end='' )
		for i in range(0, self.cells_in_series):
			print( '{:5} '.format(i+1), end='' )
		print("")

		print("Cell voltages : ", end='' )
		for i in range(0, self.cells_in_series):
			print( '{:5} '.format(self.cell_v[i]), end='' )
		print("")
		print("Status:         ", end='' )
		for i in range(0, self.cells_in_series):
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


# THIS CLASS WILL BE DEPRECATED
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


	def __init__(self, adr, id, cells_in_series, name=None):
		self.cells_in_series = cells_in_series
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
		self.Battery = BATTERY(self.cells_in_series)
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
		new_sample = BATTERY(self.cells_in_series);
		for i in range(0,5):
			# print( "Sending command3 ", self.cmd03 )
			# print(bytes.fromhex(cmd03))
			self.bt_RD.data=b""
			self.bt_dev.writeCharacteristic( self.data_characteristic, bytes.fromhex(self.cmd03), True )
			while self.bt_dev.waitForNotifications(0.2):
				# print("waiting...")
				continue
			
			if IsMsgComplete( self.bt_RD.data, 0x03 ):
				reply_ok = True
				break;

		if reply_ok:
			# print("The reply is ok")
			new_sample.DecodeMsg03( self.bt_RD.data )
			reply_ok = False

			for i in range(0,5):
				# print( "Sending command4 ", cmd04 )
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

	def EvaluateHelper(self, values, sanity_min, sanity_max, precision):
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
		self.Battery.Total_voltage = self.EvaluateHelper( values, cfg['PROCESSING_PARAMS']['SANITYMINIMUMVOLTAGE'], cfg['PROCESSING_PARAMS']['SANITYMAXIMUMVOLTAGE'], cfg['PROCESSING_PARAMS']['SYSTEMPRECISION']);

		# add the times
		self.Battery.batt_time = self.BatterySamples[i].batt_time
		self.Battery.cells_time = self.BatterySamples[i].cells_time

		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Current_charge )
		self.Battery.Current_charge = self.EvaluateHelper( values, -50, 50, systemPrecision);

		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Current_discharge )
		self.Battery.Current_discharge = self.EvaluateHelper( values, -50, 50, systemPrecision);

		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Remaining_capacity )
		self.Battery.Remaining_capacity = self.EvaluateHelper( values, 0, 250, systemPrecision);

		values = []
		for i in range(0,self.iSamples):
			values.append( self.BatterySamples[i].Typical_capacity )
		self.Battery.Typical_capacity = self.EvaluateHelper( values, 0, 250, systemPrecision);

		for c in range(0, self.cells_in_series):
			self.Battery.cell_b[c]=0
			for i in range(0,self.iSamples):
				self.Battery.cell_b[c] += (self.BatterySamples[i].Balance >> c) & 1

		for c in range(0, self.cells_in_series):
			values = []
			for i in range(0,self.iSamples):
				values.append( self.BatterySamples[i].cell_v[c] )
			self.Battery.cell_v[c] = self.EvaluateHelper( values, 1, 4.3, systemPrecision);

	def Upload(self, pg_cursor, now_time):
		cell_b = []
		cell_v = []
		col_names = ["cell%d" % i for i in range(self.cells_in_series)]
		for i in range(self.cells_in_series): cell_v.append(str(self.Battery.cell_v[i]*1000))
		for i in range(self.cells_in_series): cell_b.append(str(self.Battery.cell_b[i]*1000))

		if cfg['SAVE'].getboolean('USE_LOCAL_POSTGRES'):
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
		elif cfg['SAVE'].getboolean('SAVEDATAONLINE'):
			print("  %s: Saving the collected data to the remote db..." % self.Battery.batt_time)
			
			# we are saving the data to the online database
			self.batt_stats = (self.Battery_id, self.Battery.batt_time, self.Battery.Total_voltage, self.Battery.Current_charge, self.Battery.Current_discharge, self.Battery.Remaining_capacity, 0, 0.0)
			# print(batt_stats)
			
			# now save the cell voltages
			self.cells_v = [ (self.Battery_id, self.Battery.cells_time, i, self.Battery.cell_v[i]) for i in range(self.cells_in_series) ]
			self.cells_b = [ (self.Battery_id, self.Battery.cells_time, i, self.Battery.cell_b[i]) for i in range(self.cells_in_series) if self.Battery.cell_b[i] != 0 ]

			remote_conn = mysql.connector.connect(option_files='grafana-db-config')
			insert_cursor = remote_conn.cursor(prepared=True)

			# save the data
			insert_cursor.execute( batt_status_q, self.batt_stats )
			insert_cursor.executemany( cell_status_q, self.cells_v )
			insert_cursor.executemany( cell_balancing_q, self.cells_b )
			
			remote_conn.commit()
			print("Saving to remote db finished...")
			
			insert_cursor.close()
			remote_conn.close()
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


# THIS FUNCTION HAS BEEN MOVED TO CLASS MessageProcessing.check_command_reply
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


# THIS FUNCTION WILL BE DEPRECATED
# Register a handler for the timeout
def handler(signum, frame):
	print("Stuck... lets add this data to be sent later..")
	raise TimeoutException("Stuck somewhere...")


# THIS SIGNAL CALL WILL BE DEPRECATED
# Register the signal function handler and define a timeout 
# We might not need this!!
signal.signal(signal.SIGALRM, handler)

class BMSDevice:
	"""
	Defines a BMS device that we can connect to and read data from it

	Ideally one BMS is connected to 1 battery
	"""
	def __init__(self, adr, id_, no_series_cells, name):
		self.adr = adr
		self.id = id_
		self.name = name
		self.connected = False
		self.bt_dev = None
		self.writable_characteristics = []
		self.data_characteristic = None
		self.no_series_cells = no_series_cells
		
		# inherited blindly from prev code
		self.bt_RD = ReadDelegate()

		# command sequence to be sent in order to obtain the battery information
		self.cmd03 = "DDA50300FFFD77"
		self.cmd04 = "DDA50400FFFC77"
		self.cmd05 = "DDA50500FFFB77"

		# these read commands should be sent in the order defined in the array
		self.read_commands = [
			{'code': 0x03, 'command': "DDA50300FFFD77"},			# battery details
			{'code': 0x04, 'command': "DDA50400FFFC77"} 			# cell voltages
			# {'code': 0x05, 'command': "DDA50500FFFB77"}				# BMS Name
		]
		
	def connect(self, no_connect_tries):
		if ENV_ROLE == 'DEV': print("Trying %d times to connect to %s BMS" %  (no_connect_tries, self.name))
		for tries in range(0, no_connect_tries):
			try:
				if ENV_ROLE == 'DEV': print("\tTrying to connect (%d)...." % tries)
				# create the top level peripheral for this device
				self.bt_dev = btle.Peripheral(self.adr, btle.ADDR_TYPE_PUBLIC, 0)
				self.bt_dev.withDelegate(self.bt_RD)
				
				# loop through the characteristics and test the writable ones
				for svc in self.bt_dev.getServices():
					# get the characteristics of this services
					all_characteristics = svc.getCharacteristics()
					
					for characteristic in all_characteristics:
						if re.search('WRITE', characteristic.propertiesToString()):
							self.writable_characteristics.append(characteristic.getHandle())

				# all is good, so alter the connected flag and exit the loop
				self.connected = True
				if ENV_ROLE == 'DEV': print("\t...connected")
				break
			except btle.BTLEDisconnectError as e:
				if ENV_ROLE == 'DEV': print("Bluetooth connect error.  Resetting.")

				os.system("sudo hciconfig hci0 reset")
				time.sleep(0.5)
				continue
			except Exception as e:
				if ENV_ROLE == 'DEV': print("Some error %s: '%s'\n\tSleeping for %d seconds before retrying " % (self.name, str(e), int(cfg['BLUETOOTH']['SLEEP_TIME_BETWEEN_CONNECTION_ATTEMPTS'])))
				if USE_SENTRY: sentry.captureException()
				
				time.sleep(int(cfg['BLUETOOTH']['SLEEP_TIME_BETWEEN_CONNECTION_ATTEMPTS']))
				continue

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
				if ENV_ROLE == 'DEV': print(str(e))
				if USE_SENTRY: sentry.captureException()

				continue

	def read_data(self, db):
		try:
			if not self.connected:
				if ENV_ROLE == 'DEV': print("The BMS is not connected, reconnecting to it...")
				self.connect(5)
				
				# sleep for some time to allow the connection to stabilise
				time.sleep(2)
				if not self.connected:
					raise BMSConnectionError("Failed to connect to %s BMS" % self.name)

				if self.data_characteristic is None:
					self.determine_data_characteristic()

			
			msg_processing = MessageProcessing()
			
			# probe the BMS for battery stats using 1st command
			for cmd in self.read_commands:
				reply_ok = False

				for i in range(0, int(cfg['PROCESSING_PARAMS']['NO_READ_TRIES'])):
					self.bt_RD.data = b""
					self.bt_dev.writeCharacteristic(self.data_characteristic, bytes.fromhex(cmd['command']), True)

					# wait max 1 sec for a notification from the BMS.
					# The notification can come earlier than the 1sec and the code execution will continue
					while self.bt_dev.waitForNotifications(1.0): continue
			
					if msg_processing.check_command_reply(self.bt_RD.data, cmd['code']):
						reply_ok = True
						break				# break from the NO_READ_TRIES loop

				if reply_ok == False:
					# tried reading data from the BMS but failed!
					# Is the already collected data enough?
					# If command 0x04 or 0x05 fails and 0x03 succeeds, can I just process 0x03??
					# for now, if any command fail, raise an exception of a read error
					raise BMSReadError("Failed getting a complete reading from the BMS")

				# print("The reply is ok")
				decoded_data = msg_processing.decode_received_reply(self.bt_RD.data, cmd['code'], self.no_series_cells)

				# save this data to the database
				db.save_collected_data(self.adr, decoded_data, cmd['code'])
		
		except CheckSumError as e:
			if ENV_ROLE == 'DEV': print(str(e))
			if USE_SENTRY: sentry.captureMessage(str(e))


class MessageProcessing:
	"""
	A class to process the messages received from the BMS device
	"""
	def __init__(self):
		pass

	def check_command_reply(self, data, cmd):
		# check if the received message is complete
		try:
			if len(data) < 6: return False								# impossibly short
			elif data[1] != cmd: return False							# reply to wrong command
			elif data[3]+7 != len(data): return False					# length mismatch
			elif data[0] != 0xdd or data[-1]!=0x77: return False		# no start / end byte
			elif data[2] != 0: return False								# not an "OK" response

			# seems we have a complete message, lets confirm the checksum
			checksum=0;
			for i in range(2,data[3]+4):
				checksum = checksum + data[i]

			checksum = (checksum^0xffff)+1
			if ( data[-3] != checksum>>8 ) or ( data[-2] != checksum&0xff ):
				raise CheckSumError("A complete reply '%s' from the command '%s' was received but the checksums dont match" % (data, cmd))

			# if ENV_ROLE == 'DEV': print("Received reply for '%s' = %s (%s)" % (cmd, data, data.hex()))
			return True

		except Exception as e:
			if ENV_ROLE == 'DEV': print(str(e))
			if USE_SENTRY: sentry.captureException()

	def decode_received_reply(self, data, cmd, no_series):
		if cmd == 0x03: return self.decode_command_03(data)
		elif cmd == 0x04: return self.decode_command_04(data, no_series)

	def decode_command_03(self, data):
		# decode the received battery information
		try:
			d_data = {}
			# get the total voltage
			d_data['total_valtage'] = int.from_bytes(data[4:6], byteorder='big')/100.0
			
			# determine whether its charging or discharging
			d_data['current'] = int.from_bytes(data[6:8], byteorder='big', signed=True)/100.0
			d_data['charge_status'] = 'Charging' if d_data['current'] > 0 else 'Discharging'
			d_data['charge_current'] = d_data['current'] if d_data['current'] >= 0 else 0
			d_data['discharge_current'] = d_data['current'] if d_data['current'] < 0 else 0

			d_data['remaining_capacity'] = int.from_bytes(data[8:10], byteorder='big', signed=True)/100.0

			d_data['batt_capacity'] = int.from_bytes(data[10:12], byteorder='big', signed=True)/100.0
			d_data['cycles'] = int.from_bytes(data[12:14], byteorder='big', signed=True)
			d_data['is_balanced'] = int.from_bytes(data[16:18], byteorder='big', signed=False)
			d_data['protection'] = int.from_bytes(data[20:22], byteorder='big')

			d_data['batt_time'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

			if ENV_ROLE == 'DEV': print('\nDecoded command battery info')
			if ENV_ROLE == 'DEV': print(d_data)

			return d_data

		except Exception as e:
			if ENV_ROLE == 'DEV': print(str(e))
			if USE_SENTRY: sentry.captureException()

	def decode_command_04(self, data, no_series):
		# decode the received cell voltages
		try:
			d_data = {}

			for i in range(0, no_series):
				d_data[i] =  int.from_bytes(data[(4+i*2):(6+i*2)], byteorder='big')/1000.0

			d_data['cells_time'] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

			if ENV_ROLE == 'DEV': print('\nDecoded cell voltages')
			if ENV_ROLE == 'DEV': print(d_data)
			return d_data

		except Exception as e:
			if ENV_ROLE == 'DEV': print(str(e))
			if USE_SENTRY: sentry.captureException()


class Database:
	"""
	A class to handle the database connections
	"""
	def __init__(self):
		self.remote_conn = None
		self.batteries = None
		self.connect()

	def connect(self):
		if SAVE_DATA_ONLINE:
			try:
				if ENV_ROLE == 'DEV': print("Initiating connection to remote database...")
				self.remote_conn = mysql.connector.connect(option_files='grafana-db-config')

				# prepare the connection details
				insert_cursor = self.remote_conn.cursor(prepared=True)
				# batt_status_q = "INSERT INTO batt_status(batt_id, datetime, voltage, charge, discharge, rem_capacity, cycles, balance) VALUES(%d, %s, %f, %f, %f, %f, %d, %f)"
				self.batt_status_q = "INSERT INTO batt_status(batt_id, datetime, voltage, charge, discharge, rem_capacity, cycles, balance) VALUES(%s, %s, %s, %s, %s, %s, %s, %s)"
				self.cell_status_q = "INSERT INTO cell_status(batt_id, datetime, cell_no, cell_v) VALUES(?, ?, ?, ?)"
				self.cell_balancing_q = "INSERT INTO cell_balancing(batt_id, datetime, cell_no, cell_a) VALUES(?, ?, ?, ?)"

				# update the batteries with info from the database
				cursor = self.remote_conn.cursor(dictionary=True)
				# cursor.execute("SELECT id from batt_info where bms_mac = %(mac)s")
				cursor.execute("SELECT id, name, bms_mac from batt_info where is_active = 1")
				self.batteries = []
				for row in cursor:
					print(row['bms_mac'])
					self.batteries.append({'id': row['id'], 'name': row['name'], 'addr': row['bms_mac']})

				if ENV_ROLE == 'DEV': print("Remote database connection succeeded...\n\n")
				cursor.close()
				self.remote_conn.close()
			except Exception as e:
				if ENV_ROLE == 'DEV': print(str(e))
				if USE_SENTRY: sentry.captureException()
		else:
			self.remote_conn = None

	def save_collected_data(self, bms_addr, data, cmd):
		if SAVE_DATA_ONLINE:
			self.save_data_online(bms_addr, data, cmd)
		
		if SAVE_2_POSTGRES:
			self.save_data2postgres(bms_addr, data, cmd)

		if PUBLISH_2_MQTT:
			self.publish_2_mqtt(bms_addr, data, cmd)

	def save_data_online(self, bms_addr, data, cmd):
		try:
			self.remote_conn = mysql.connector.connect(option_files='grafana-db-config')
			insert_cursor = self.remote_conn.cursor(prepared=True)

			for batt in self.batteries:
				if batt['addr'] == bms_addr:
					if cmd == 0x03:
						# saving the battery information
						# SAMPLE DATA
						# {'total_valtage': 26.14, 'current': -4.22, 'charge_status': 'Discharging', 'charge_current': 0, 'discharge_current': -4.22, 'remaining_capacity': 0.0, 'batt_capacity': 30.0, 'cycles': 2, 'is_balanced': 0, 'protection': 0, 'batt_time': '2020-12-17 19:12:44'}
						# END OF SAMPLE DATA
						print("\n%s: Saving the battery (%s) data to the remote db..." % (data['batt_time'], bms_addr))
						batt_stats = (batt['id'], data['batt_time'], data['total_valtage'], data['charge_current'], data['discharge_current'], data['remaining_capacity'], data['cycles'], data['is_balanced'])

						# save the data						
						insert_cursor.execute(self.batt_status_q, batt_stats)

					elif cmd == 0x04:
						# saving the cells information
						# SAMPLE DATA
						# {0: 3.691, 1: 3.736, 2: 3.739, 3: 3.739, 4: 3.742, 5: 3.731, 6: 3.763, 'cells_time': '2020-12-17 19:12:48'}
						# END OF SAMPLE DATA
						print("\n%s: Saving the cells data to the remote db..." % data['cells_time'])
						self.cells_v = [ (batt['id'], data['cells_time'], i, data[i]) for i in range(int(cfg['BATT']['CELLS_IN_SERIES'])) ]

						# save the data
						insert_cursor.executemany(self.cell_status_q, self.cells_v)
						

			self.remote_conn.commit()
			insert_cursor.close()
			self.remote_conn.close()
			if ENV_ROLE == 'DEV': print("\tSaving to remote db finished...")

		except Exception as e:
			if ENV_ROLE == 'DEV': print(str(e))
			if USE_SENTRY: sentry.captureException()

	def save_data2postgres(self, bms_addr, data, cmd):
		try:
			self.pg = psycopg2.connect(database = cfg['POSTGRES']['DB'], user = cfg['POSTGRES']['USER'], password = cfg['POSTGRES']['PASS'], host = cfg['POSTGRES']['HOST'])
			self.pg_cursor = self.pg.cursor()

			# dragonflyuk please add the code for saving offline to postgres

		except Exception as e:
			if ENV_ROLE == 'DEV': print(str(e))
			if USE_SENTRY: sentry.captureException()

	def publish_2_mqtt():
		try:
			# dragonflyuk please add the code for publishing to mqtt
			# 
            print("Publishing collected data to the MQTT server...")
            # we are saving the data to the online database
            batt_stats = [{'topic':mqttTopic+(self.Name)+"/id", 'payload':self.Battery_id},
                          {'topic':mqttTopic+(self.Name)+"/time", 'payload':self.Battery.batt_time}, 
                          {'topic':mqttTopic+(self.Name)+"/total_voltage", 'payload':self.Battery.Total_voltage}, 
                          {'topic':mqttTopic+(self.Name)+"/charge_current", 'payload':self.Battery.Current_charge}, 
                          {'topic':mqttTopic+(self.Name)+"/discharge_current", 'payload':self.Battery.Current_discharge}, 
                          {'topic':mqttTopic+(self.Name)+"/remaining_capacity", 'payload':self.Battery.Remaining_capacity}]
            print(batt_stats)
            mqtt.multiple(batt_stats, hostname = cfg['MQTT']['HOST'], auth = cfg['MQTT']['AUTH'])

            # now save the cell voltages
            cells_v = []
            for i in range(cells_in_series):
                cells_v.append({'topic':mqttTopic+(self.Name)+"/cell"+str(i)+"_voltage", 'payload':self.Battery.cell_v[i]})
            print(cells_v)
            mqtt.multiple(cells_v, hostname=mqttHostname, auth=mqttAuth)
            print("Publish to MQTT finished...")

		except Exception as e:
			if ENV_ROLE == 'DEV': print(str(e))
			if USE_SENTRY: sentry.captureException()


while True:
	if ENV_ROLE == 'DEV': print('Starting the new main loop')
	try:
		devices = []
		# loop through the defined bms bt addresses and initialize their classes
		ind = 1
		batts = dict(cfg['BATTERIES'])
		db = Database()

		for bt_name, bv in batts.items():
			bt_vals = json.loads(bv)
			bms_device = BMSDevice(bt_vals['addr'], bt_vals['id'], int(cfg['BATT']['CELLS_IN_SERIES']), bt_name)
			devices.append(bms_device)

		main_start_time = datetime.datetime.now()
		if ENV_ROLE == 'DEV': print("Start reading the data from the BMS...")
		for bms in devices:
			# now read and process the data
			bms.read_data(db)

		if ENV_ROLE == 'DEV': print("\nFinished a loop of all the devices. Resetting the bluetooth connection and sleeping for %d seconds" % int(cfg['PROCESSING_PARAMS']['LOOP_SLEEP_TIME']))
		os.system("sudo hciconfig hci0 reset")
		time.sleep(int(cfg['PROCESSING_PARAMS']['LOOP_SLEEP_TIME']))

	except Exception as e:
		if ENV_ROLE == 'DEV': print(str(e))
		if USE_SENTRY: sentry.captureMessage(str(e))

		# we are in the main loop, so just ignore this message and start again
		# pass



"""
THIS IS THE OLD LOOP... IT WILL BE DELETED


timed_out_data = []

while True:
	print("Starting the main loop...")

	BMSs = []
	# loop through the defined bms bt addresses and initialize their classes
	ind = 1
	for bt in cfg['BLUETOOTH']['BATTERIES']:
		bms_c = BMS_class(bt['addr'], bt['id'], cfg['BATT']['CELLS_IN_SERIES'], bt['name'])
		BMSs.append(bms_c)

	start_time = datetime.datetime.now()

	if ENV_ROLE == 'DEV': print("Collecting samples...")
	while True:
		time.sleep(3)
		for bms in BMSs:
			try:
				if bms.data_characteristic is None:
					BMS.determine_data_characteristic()

				bms.CollectSample()
			except btle.BTLEDisconnectError as e:
				if USE_SENTRY: sentry.captureMessage("Bluetooth disconnected. Trying to connect it again.", level='info')

				if ENV_ROLE == 'DEV':
					print(str(e))
					print("Bluetooth disconnect error.  Resetting.")

				os.system("sudo hciconfig hci0 reset")
				time.sleep(10)

				bms = BMS_class(bms.adr, bms.id)   # try reconnect
				if ENV_ROLE == 'DEV': print("Reconnecting BMS#"+str(bms.id) )
				continue

			except Exception as e:
				if ENV_ROLE == 'DEV': print(str(e))
				if USE_SENTRY: sentry.captureException()

		now_time = datetime.datetime.now()
		sample_duration = datetime.timedelta(minutes=0.5)
		#elapsed_time = now_time - start_time

		# on every 5th minute, but minimum 1 minute elapsed
#		if now_time.minute % 5 == 0 and now_time.minute > start_time.minute+2:
		#if now_time.minute >= start_time.minute+5:
		if now_time >= (start_time + sample_duration):
			break;

	print("")

	try:
		pg_cursor = None
		if cfg['SAVE']['USE_LOCAL_POSTGRES']:
			pg = psycopg2.connect(database = cfg['POSTGRES']['DB'], user = cfg['POSTGRES']['USER'], password = cfg['POSTGRES']['PASS'], host = cfg['POSTGRES']['HOST'])
			pg_cursor = pg.cursor()

		for BMS in BMSs:
			BMS.Evaluate()

			if BMS.connected and BMS.iSamples>0:
				print('======== Battery #', BMS.id, " ========", sep="")
				BMS.Battery.Output()
				# put a timer to monitor this function to avoid chocking
				signal.alarm(cfg['PROCESSING_PARAMS']['FUNCTIONTIMEOUT'])
				BMS.Upload(pg_cursor, now_time)
				signal.alarm(0)						# cancel the timeout if the function returns successfully
			del BMS

		del BMSs
	
	except TimeoutException as e:
		print("Not saved data....")

		print(BMS.batt_stats)
		print(BMS.cells_v)
		print(BMS.cells_b)

		with open("stuck_data.txt", "a") as outfile:
			outfile.write("bs:%s\n" % ",".join([str(x) for x in BMS.batt_stats]))
			outfile.write("cv:%s\n" % ",".join([str(x) for x in BMS.cells_v]))
			outfile.write("cb:%s\n" % ",".join([str(x) for x in BMS.cells_b]))
			outfile.write("\n")

	except mysql.connector.Error as e:
		if ENV_ROLE == 'DEV': print("There was an error while connecting to the database: %s" % str(e))
		if USE_SENTRY: sentry.captureException()

		with open("stuck_data.txt", "a") as outfile:
			outfile.write("bs:%s\n" % ",".join([str(x) for x in BMS.batt_stats]))
			outfile.write("cv:%s\n" % ",".join([str(x) for x in BMS.cells_v]))
			outfile.write("cb:%s\n" % ",".join([str(x) for x in BMS.cells_b]))
			outfile.write("\n")
		pass

	except Exception as e:
		if ENV_ROLE == 'DEV': print(str(e))
		if USE_SENTRY: sentry.captureException()

		with open("stuck_data.txt", "a") as outfile:
			outfile.write("bs:%s\n" % ",".join([str(x) for x in BMS.batt_stats]))
			outfile.write("cv:%s\n" % ",".join([str(x) for x in BMS.cells_v]))
			outfile.write("cb:%s\n" % ",".join([str(x) for x in BMS.cells_b]))
			outfile.write("\n")
		pass

	query=( "INSERT INTO battery_minute_data (time, battery_id, voltage, current_charge, current_discharge, remaining_capacity) " +
			"SELECT time, 0, AVG(voltage), SUM(current_charge), SUM(current_discharge), SUM(remaining_capacity) FROM battery_minute_data " +
			"WHERE time=\'"+now_time.strftime("%Y-%m-%d %H:%M") + "\' GROUP BY 1")

	if cfg['SAVE']['USE_LOCAL_POSTGRES']:
		pg_cursor.execute(query)
		pg.commit()
		pg.close
	else:
		# print(query)
		print('')

	os.system("sudo hciconfig hci0 reset")
	print("sleep")
	time.sleep(10)
"""
