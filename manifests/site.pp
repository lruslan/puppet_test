# site.pp
# This is the "starting point" of the puppetrun

# define the nodes here
node default {
  # Check facts "spil_environment", "platform" to decide
  # which class include
  # For the 'puppet_test' environment use separate logic
  if $spil_environment == 'puppet_test' {
    notify { 'Running in a test mode': }
    notify { "Base : \"roles::${::platform}::base\"": }
    class { "roles::${::platform}::base": }
    if defined("${::module}::test"){
      notify { "Test module: \"${::module}::test\"": }
      class { "${::module}::test": }
    }
  } else {
    # All normal environments processed here
    if $platform {
      notify { "Check roles::${::platform}::${::role} for platform ${::platform}": }
      if defined("roles::${::platform}::${::role}"){
        notify { "Role ${::role} defined for platform ${::platform}": }
        class { "roles::${::platform}::${::role}": }
      } else {
        notify { "Role is not defined - use \"roles::${::platform}::spil_base\"": }
        class { "roles::${::platform}::base": }
      }
    }
    else {
        notify { 'Role and platform is not defined - use default "roles::spil_base"': }
        class { 'roles::spil_base': }
    }
  }
}
