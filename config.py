#########################################################
# NAME: Alex_Bilat
# COURSE: ICS4U
# FILE: config.py
# DESCRIPTION: Configs for the main file
#########################################################

# Importing
import requests
from bs4 import BeautifulSoup
import sys
import os
import time
from collections import Counter
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# Urls
url = 'https://www.ontario.ca/page/public-sector-salary-disclosure' # I wanna scrape this!
api_url = "https://data.ontario.ca/api/3/action/datastore_search" # KCAN API URL

# Outputs
output_path = 'output.txt' # Output here

