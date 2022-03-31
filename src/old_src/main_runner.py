import os
from curie_calculator import *
from status_check import vasprun_checker
input_folder, num_of_structures, fake_magnetic_atoms, spin = input_reader()
initial_path = os.getcwd()
run_enum(input_folder)
get_structures(num_of_structures=num_of_structures)
vasp_inputs_creator(num_of_structures=num_of_structures)
siman_inputs_creator(num_of_structures=num_of_structures)
enum_out_collector()
os.chdir(initial_path)
submit_all_jobs(input_folder)
vasprun_checker(input_folder)
