import requests
import yaml

response = requests.get(
    ('https://pdc.fedoraproject.org/rest_api/v1/unreleasedvariants/?variant_version=master'
     '&page_size=-1&variant_id=bootstrap')
)

data = response.json()
item = data[0]
item['modulemd'] = yaml.load(item['modulemd'])
print(yaml.dump(item))
