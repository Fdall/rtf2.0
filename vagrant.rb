# -*- mode: ruby -*-
# vi: set ft=ruby :

$vagrant_systems = {
  "debian11" => "debian/bullseye64",
  "debian12" => "debian/bookworm64",
  "ubuntu20_04" => "normation/ubuntu-20-04-64",
  "ubuntu22_04" => "ubuntu/jammy64",
}

require 'json'

# Configure a complete platform by just providing an id and a json file
def platform(config, platform_name)
  datastate = ".rtfstate"
  unless File.file?(datastate)
    puts "File " + datastate + " doesn't exist, aborting!"
    exit(1)
  end
  file = open(datastate)
  json = file.read
  data = JSON.parse(json)
  platform_data = data[platform_name]

  machines = platform_data['hosts'].keys()
  machines.each do |host_name|
    machine = platform_data['hosts'][host_name]
    # Configure
    config.vm.define host_name do |cfg|
      unless $vagrant_systems.include? machine['system'] then
        puts "Unknown system #{machine['system']}"
      end
      cfg.vm.synced_folder "shared", "/vagrant", disabled: true, SharedFoldersEnableSymlinksCreate: false
      cfg.vm.provision "ansible" do |ansible|
        ansible.become = true
        ansible.compatibility_mode = "2.0"
        ansible.extra_vars = {
          datastate: platform_data
        }
        ansible.verbose = true

        if machine.key?('rudder-setup') then
          ansible.groups = {
            machine['rudder-setup'] => [ host_name ]
          }
        end

        ansible.playbook = "playbook.yml"
      end
      vagrant_machine(cfg, machine)
    end
  end
end


# Configure a single machine
def vagrant_machine(cfg, machine)
  cfg.vm.box = $vagrant_systems[machine['system']]
  cfg.vm.provider :virtualbox do |vm|
    vm.customize ['modifyvm', :id, '--cableconnected1', 'on']
    vm.name   = machine['long-name']
    vm.memory = machine['ram']
    vm.cpus   = machine.key?('cpus') ? machine['cpus'] : 1
  end
  if machine['rudder-setup'] =~ /server/ then
    cfg.vm.network :forwarded_port, guest: 80, host: machine['http-port']
    cfg.vm.network :forwarded_port, guest: 443, host: machine['https-port']
  end

  # common conf
  cfg.vm.network :private_network, ip: machine['ip']
  cfg.vm.hostname = machine['short-name']
  if machine['system'] =~ /win/ then
    cfg.ssh.insert_key = false
    cfg.ssh.username = 'Administrator'
  end
end
