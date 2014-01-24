class my_module($test_parameter = 'Hi!'){
  notify { "my_module says: ${test_parameter}": } 
}
