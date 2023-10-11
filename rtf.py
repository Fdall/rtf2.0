import os
import re
import json
import jinja2
from ipaddress import IPv4Network

class Datastate:
  def __init__(self):
    self.path = ".rtfstate"
    self.data = self.load()

  def load(self):
    if not os.path.isfile(self.path):
      return {}
    return loadJson(self.path)

  def write(self):
    with open(self.path, "w") as fd:
      fd.write(json.dumps(self.data, sort_keys=True, indent=2))
    v = Vagrantfile()
    v.write(self.data.keys())

  def removePlatform(self, platformName):
    self.data = self.load()
    if platformName in self.data:
      self.data.pop(platformName)
      self.write()

  def update(self, platform_names):
    self.data = self.load()
    userState = {}
    for platform in platform_names:
      try:
        userState[platform] = {
          "hosts": Platform(platform).data
        }
      except Error as e:
        print(e)
        print("Could not parse the platform '" + platform + "'. Skipping it.")
    self.data = mergeDicts(userState, self.data)
    self.write()

    # Check that every platform has an assigned subnet
    for k in self.data.keys():
      self.assignSubnet(k)
      # Check that every host has an IP
      for h in self.data[k]['hosts'].keys():
        self.assignIP(k, h)
      # Check that every webapp has an http and https port assigned
      for h in self.data[k]['hosts'].keys():
        self.assignPort(k, h, 'http-port')
        self.assignPort(k, h, 'https-port')

  def getAllUsedPorts(self):
    inUse = []
    for platformName, platformContent in self.data.items():
      for hostname, host in platformContent['hosts'].items():
        if 'http-port' in host:
          inUse.append(host['http-port'])
        if 'https-port' in host:
          inUse.append(host['https-port'])
    return inUse

  def getNextAvailablePort(self):
    inUse = self.getAllUsedPorts()
    port = 8080
    while port in inUse:
      port += 1
    return port

  # keyName is expected to be https-port or http-port
  def assignPort(self, platformName, hostname, keyName):
    if self.data[platformName]['hosts'][hostname]['rudder-setup'] != 'server':
      return
    if keyName not in self.data[platformName]['hosts'][hostname]:
      port = self.getNextAvailablePort()
      self.data[platformName]['hosts'][hostname][keyName] = port
      print("Assign port '" + str(port) + "' to the host '" + hostname + "'")
      self.write()

  def assignIP(self, platformName, hostname):
    if 'ip' in self.data[platformName]['hosts'][hostname]:
      return
    ip = self.getNextAvailableIP(platformName)
    self.data[platformName]['hosts'][hostname]['ip'] = ip
    print("Assign ip '" + ip + "' to the host '" + hostname + "'")
    self.write()
    return

  def getAllUsedIP(self, platformName):
    inUse = []
    for hostname, conf in self.data[platformName]['hosts'].items():
      if 'ip' in conf:
        inUse.append(conf['ip'])
    return inUse

  def getNextAvailableIP(self, platformName):
    # Assume that the subnet is defined
    inUse = self.getAllUsedIP(platformName)
    network = IPv4Network(self.data[platformName]['subnet'] + '/24')
    inUse.append(str(network[1]))
    print(inUse)
    hosts_iterator = (host for host in network.hosts() if str(host) not in inUse)
    return str(next(hosts_iterator))

  def assignSubnet(self, platformName):
    if 'subnet' in self.data[platformName]:
      return
    subnet = self.getNextAvailableSubnet()
    self.data[platformName]['subnet'] = subnet
    print("Assign subnet '" + subnet + "' to the platform '" + platformName + "'")
    self.write()
    return

  def getAllUsedSubnets(self):
    inUse = []
    for pfContent in self.data.values():
      if 'subnet' in pfContent:
        inUse.append(pfContent['subnet'])
    return inUse

  def getNextAvailableSubnet(self):
    inUse = self.getAllUsedSubnets()
    index = 0
    subnet = "192.168." + str(index) + ".0"
    while subnet in inUse:
      index += 1
      subnet = "192.168." + str(index) + ".0"
    print("Next available subnet: " + subnet)
    return subnet

class Vagrantfile:
   def __init__(self):
     self.path = "Vagrantfile"
     self.templatePath = "Vagrantfile.jinja"
     self.platforms = self.parse()

   def write(self, platform_names):
     with open(self.templatePath) as ft:
       rendered = jinja2.Template(ft.read()).render(platforms=platform_names)
       with open(self.path, "w") as fd:
         fd.write(rendered)
     return

   def parse(self):
     if not os.path.isfile(self.path):
       return []
     existingPlatforms = []
     platform_re = re.compile(r"platform\('(\w+)'\)")
     with open("Vagrantfile", "r+") as fd:
      for l in fd.readlines():
        m = platform_re.match(l)
        if m:
          existingPlatforms.append(m.group(1))
     return existingPlatforms

   def add_platform(self, platform_name):
     if platform_name not in self.platforms:
       self.platforms.append(platform_name)
       self.write(self.platforms)

   def remove_platform(self, platform_name):
     if platform_name in self.platforms:
       self.platforms.remove(platform_name)
       self.write(self.platforms)

class Platform:
    def __init__(self, name):
      self.name = name
      self.filename = "platforms/" + name + ".json"
      self.data = self.fromJson()

    def getDefaultRam(self, rudderSetup, system):
      match (rudderSetup, system):
        case ('server', _):
          return 2048
        case ('relay', _):
          return 512
        case (_, win):
          return 2048
        case (_, solaris):
          return 1024
        case (_, _):
          return 256


    def fromJson(self):
      if not os.path.isfile(self.filename):
        print("Platform " + self.name + " does not exist")
        exit(1)
      rawData = loadJson(self.filename)
      if 'default' not in rawData:
          print("No 'default' key in the platform json file!")
          exit(1)

      data = {}
      for hostname, hostData in rawData.items():
        if hostname != "default":
          partialMerge = rawData['default'] | hostData
          longName = self.name + '_' + hostname
          extraHostData = {
            "short-name": hostname,
            "long-name": longName,
            "ram": self.getDefaultRam(partialMerge.get('rudder-setup'), partialMerge.get('system'))
          }
          # Apply a first key level override on the data
          data[longName] = extraHostData | partialMerge
      return data


def loadJson(filename):
  """ Load a commented json """
  # read json from file
  file = open(filename, 'r')
  data = file.read()
  file.close()
  data = re.sub("\\/\\/.*", "", data)
  try:
    return json.loads(data)
  except Exception as e:
    print("JSON syntax error in " + filename)
    print(e.message)
    exit(3)

# Deep merge but alters the destination in place
def mergeDicts(source, destination):
  for key, value in source.items():
    if isinstance(value, dict):
      node = destination.setdefault(key, {})
      mergeDicts(value, node)
    else:
        destination[key] = value
  return destination
