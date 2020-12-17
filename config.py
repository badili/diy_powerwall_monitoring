

# BMS bluetooth addresses and their indexes
batteries = [{'id': 1, 'name': 'woodburner', 'addr': 'A4:C1:38:B9:7C:DF'}]
post2db = False
saveDataOnline = False
publishMQTT = True
cells_in_series = 4
sleep_time_between_connection_attempts = 3      # in seconds

sanityMinimumVoltage = 11
sanityMaximumVoltage = 15
systemPrecision = 3             # Allow 3 decimal places

mqttTopic = "battery/"
mqttHostname = "192.168.1.3"
mqttAuth = {'username':"username", 'password':"password"}

loop = False

