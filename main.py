#!/usr/bin/env python3

import requests
import json

def site_login(mail,password,device_id,recap):
    s = requests.Session()
    payload = {
            'email':mail,
            'password': password,
            'device_id':device_id,
            'recaptcha_response': recap
    }
    res = s.post('https://p-api.delta.exchange/v2/login',json = payload)
    #s.headers.update({'authorization': json.loads(res.content)['token']})
    print(res.content)
    return(s)

session = site_login("arulmuruga.ad@gmail.com","mUs;KUfh3186!","62abf32b-6a34-4808-b614-f1ae60a82c49","03AIIukzi1QOGLl2LDMLNCCMb5mQVzTt4SOHyUoeQ2WFEcbh6FcLXuieqXLka_S8KD_H1BaACmstER6iQ2QW0M5w82EYBq8qMhiLGTynyHszek56DxLyQ1mMl1WiGjmi4203s_vg2pFllU-Q-11NngLL2OG7cZGREWqek4v1GhCtESYBEXSNT_GGh6_crLzU9Kb6zPFLKce2ZQQuhFujKg4nfUOjlwnqxr5cYBnmOSmJ7I9uqw7727CXMfew8ZEA90S64In__7u-1VmV2cgSNaDTtBRpB5jDkFTro2omFDkG2Kyt05ZbllkL7qrLxas0AoC9evKT0cN_D8wqXMoN5jczyBf9ZycglxZTtJL6yvd4HGmvQbk1D_Ljm1_LH7GWL_cDu7NE-1V5C4XgLFXPn7t8QNE_gqBuUUJ_HaBTxLDQpOme_2cMQ57s54z7LmUzM71ZaePzIAZbhaxE-onS5rwYAclnj0frte90-LUttwHtVLdewrcPPLEZK3FpUtX7yrWgIzsrSU5iHBrmhnTvaNadoLA7w1likXEA")
