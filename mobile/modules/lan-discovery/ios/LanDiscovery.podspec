Pod::Spec.new do |s|
  s.name           = 'LanDiscovery'
  s.version        = '1.0.0'
  s.summary        = 'Bonjour discovery and Wake-on-LAN magic packets for the local network'
  s.description    = 'Browses _wol-unlock._tcp via NWBrowser and sends WoL magic packets over a broadcast UDP socket.'
  s.author         = ''
  s.homepage       = 'https://docs.expo.dev/modules/'
  s.platforms      = { :ios => '15.1', :tvos => '15.1' }
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }

  s.source_files = "**/*.{h,m,mm,swift,hpp,cpp}"
end
