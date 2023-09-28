
The project aims to automate cryptocurrency option trading using Python. The automation process will allow traders to automatically execute trades based on certain criteria, such as market volatility or specific price movements.

To get started with this project, you will need to have Python 3.5 or higher installed on your system. You will also need to install the following libraries:

NumPy
pandas
matplotlib
seaborn
scikit-learn
ta
ccxt
You can install these libraries using the pip package manager by running the following command:

sh
Copy code
pip install numpy pandas matplotlib seaborn scikit-learn ta ccxt
Usage
To use this automation system, you will need to configure your API keys for your chosen cryptocurrency exchange. The supported exchanges are listed in the exchange.py file. You will need to create an account with your chosen exchange and generate API keys with trading permissions.

Once you have configured your API keys, you can run the main.py file to start the automation process. The automation process will continuously monitor the market and execute trades based on the criteria you have specified.

Strategy
The project uses standard option strategies like straddle and strangle, both short and long

Backtesting
To backtest the strategy, you can run the backtest.py file. The backtesting process will simulate the trading strategy on historical data and generate performance metrics, such as profit/loss, win rate, and maximum drawdown.

Features to be added:
GUI
notifications
PL statement generation 

Conclusion
Cryptocurrency option trading automation can be a powerful tool for traders looking to execute trades based on specific criteria. This project provides a starting point for developing an automated trading system using Python. However, it is important to note that trading cryptocurrencies involves significant risk and should only be undertaken by experienced traders.

