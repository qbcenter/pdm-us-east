sh -c "$(curl -fsSL https://raw.githubusercontent.com/Linuxbrew/install/master/install.sh)"

echo 'eval $(/home/linuxbrew/.linuxbrew/bin/brew shellenv)' >>~/.profile
sudo yum groupinstall 'Development Tools'
PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"

brew install snappy

pip install -U fastparquet
pip install -U python-snappy