# DIY Powerwall monitoring
A collection of scripts that will be used for monitoring a DIY powerwall


## Credits
Many thanks to [AJW22] (https://secondlifestorage.com/member.php?action=profile&uid=12711) for the initial code of getting the data from the cheap chinese BMS


## Hardware
- [Cheap Chinese BMS with bluetooth](https://www.alibaba.com/product-detail/3-32S-smart-bluetooth-BMS-with_62174561033.html?spm=a2700.12243863.0.0.2ce83e5fiGsusY) by [Shenzhen E-Fire Technology Development Co., Ltd.](https://cl-rd.en.alibaba.com/?spm=a2700.icbuShop.88.16.6c6e7e53YoznC8)


## Installation
1. Create a new folder and then clone the code 
```
mkdir powerwall && cd powerwall
git clone https://github.com/badili/diy_powerwall_monitoring.git
```

2. Create a virtual environment using python3.7 
*The Raspberry Pi OS comes with python 2 and python 3.7 already installed*
If python3.7 is not installed, install it. Installation steps are out of scope of this documentation

`/usr/local/bin/python3.7 -m venv env`

3. Activate the virtual environment
source env/bin/activate

4. Install the pre-requisite modules
pip install -r requirements.txt

## Running the scripts
5. xxx