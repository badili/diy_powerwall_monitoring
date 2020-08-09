# If python3 is not installed, install it
sudo apt-get update
sudo apt-get install -y build-essential tk-dev libncurses5-dev libncursesw5-dev libreadline6-dev libdb5.3-dev libgdbm-dev libsqlite3-dev libssl-dev libbz2-dev libexpat1-dev liblzma-dev zlib1g-dev libffi-dev
sudo apt-get install libreadline-gplv2-dev libncursesw5-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev openssl

wget https://www.python.org/ftp/python/3.7.0/Python-3.7.0.tgz
sudo tar zxf Python-3.7.0.tgz
cd Python-3.7.0/
sudo ./configure --with-ssl
sudo make -j 4
sudo make altinstall
/usr/local/bin/python3.7 --version

# Create a virtual environment using python3
/usr/local/bin/python3.7 -m venv env

# Activate the virtual environment
source env/bin/activate

# Install the pre-requisite modules
pip install -r requirements.txt