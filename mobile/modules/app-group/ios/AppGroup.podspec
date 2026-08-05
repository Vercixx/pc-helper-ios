Pod::Spec.new do |s|
  s.name           = 'AppGroup'
  s.version        = '1.0.0'
  s.summary        = 'Runtime discovery of the App Group this build was actually signed with'
  s.description    = 'Reads embedded.mobileprovision so re-signing tools that rewrite identifiers do not break shared storage.'
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
