# DIY Powerwall monitoring
A collection of scripts that will be used for monitoring a DIY powerwall


## Credits
Many thanks to [AJW22](https://secondlifestorage.com/member.php?action=profile&uid=12711) for the initial code of getting the data from the cheap chinese BMS


## Hardware
- [Cheap Chinese BMS with bluetooth](https://www.alibaba.com/product-detail/3-32S-smart-bluetooth-BMS-with_62174561033.html?spm=a2700.12243863.0.0.2ce83e5fiGsusY) by [Shenzhen E-Fire Technology Development Co., Ltd.](https://cl-rd.en.alibaba.com/?spm=a2700.icbuShop.88.16.6c6e7e53YoznC8)


## Bluetooth setup on the command line
*Thanks to [this tutorial](https://www.cnet.com/how-to/how-to-setup-bluetooth-on-a-raspberry-pi-3/)*
1. Turn bluetooth on and scan the nearby devices
```
sudo bluetoothctl 
agent on
default-agent
scan on
```

SQLite installation
`sudo apt-get install sqlite3 git python3-venv`

Create the database powerwall
`sqlite3 powerwall`

2. Identify the BMS and connect to it
*It ends with __xiaoxiang BMS__*
`pair [device Bluetooth address]`

3. Turn scanning off
`scan off`

4. You might also want to connect to it by
`connect [device Bluetooth address]`

5. To exit from the bluetooth interface type `quit`

## Grafana installation
A docker setup is configured to setup a grafana instance as well as a MySQL instance to save the collected data

Once the db instance is up and running, connect to it, create a user on the database that can write data from the pi and grant the user all privileges on the default database
Connect via the container `docker exec -t <db-instance> /bin/bash` or from the host `mysql -h localhost -P 9033 --protocol=tcp -u root -p`
```
create user 'youruser'@'%' identified by 'your-password';
grant all privileges on powerwall.* to 'youruser'@'%';
```

## Installation
1. Clone the code `git clone https://github.com/badili/diy_powerwall_monitoring.git`

2. Create a virtual environment using python3.7 
*The Raspberry Pi OS comes with python 2 and python 3.7 already installed*
If python3.7 is not installed, install it. Installation steps are out of scope of this documentation

```
cd diy_powerwall_monitoring
python3.7 -m venv env
```

3. Activate the virtual environment `source env/bin/activate`
4. Modify the requirements.txt file appropriately. If you are using PostgreSQL make sure to remove the comment tag
5. Install the pre-requisite modules `pip install -r requirements.txt`

## Running the scripts
5. xxx

## Resources
1. [bluepy - a Bluetooth LE interface for Python](https://ianharvey.github.io/bluepy-doc/index.html)
2. [Profile and user data over bluetooth](https://www.oreilly.com/library/view/getting-started-with/9781491900550/ch04.html#gatt_char_decl_attr)
3. [Communication protocol](https://drive.google.com/file/d/0B3UXptx89r4NZ3VLTHlVS1ZGTTQ/view)
4. [Php EpSolar Tracer](https://github.com/toggio/PhpEpsolarTracer)
5. [Communication Interface for Tracer MT-5](https://github.com/xxv/tracer)
6. [Generic Chinese Bluetooth BMS communication protocol](https://github.com/simat/BatteryMonitor/wiki/Generic-Chinese-Bluetooth-BMS-communication-protocol)