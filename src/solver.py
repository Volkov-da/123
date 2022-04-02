import os
import numpy as np
from tqdm import tqdm
from pymatgen.core import Structure
from pymatgen.io.vasp.outputs import Vasprun, Oszicar, Outcar
from siman.calc_manage import smart_structure_read
from scipy.constants import physical_constants
import matplotlib.pyplot as plt
import warnings

from read_input import update_defaults
from variables import DEFAULT_DICT
warnings.filterwarnings("ignore")

k_B = physical_constants['Boltzmann constant in eV/K'][0]


def get_ratio(path_to_structure: str, initial_atoms_num: float) -> float:
    tmp_strucuture = Structure.from_file(path_to_structure)
    ratio = len(tmp_strucuture) / initial_atoms_num
    return ratio


def count_nn(path_to_poscar: str, magnetic_atoms: list) -> dict:
    """
    calculated the number of nearest neighbors,
    to fit into the Heisenberg model.
    Get a path to POSCAR structure as an input,
    To avoid errors one should use prettified POSCAR,
    use poscar_prettifier() function first.

    Args:
        poscar_path     (str)  - path to the POSCAR file
        magnetic_atoms  (list) - two type of atoms to be treated as a magnetic
                            with an opposite spins (up/down).
                            your POSCAR should contain this two types of atoms.
    Returns:
        dict{distance : number_of_neibours}
    """
    if not os.path.exists(path_to_poscar):
        print(f'File {path_to_poscar} does not exist!')
        return None
    st = smart_structure_read(path_to_poscar)
    st = st.replic([6, 6, 6])
    out = st.nn(i=1, n=500, silent=1)

    a = list(zip(out['el'][1:], out['dist'][1:]))
    # collect all the unique distances
    unique_dist = set(round(i[1], 3) for i in a if i[0] in magnetic_atoms)
    magnetic_dist_lst = [(el, round(dist, 3))
                         for el, dist in a if el in magnetic_atoms]

    dist_neighbNum = {_: 0 for _ in unique_dist}  # key- distane, value list of
    # neighbours at 1st 2nd 3d coordination spheres

    for dist in unique_dist:
        for el, distance in magnetic_dist_lst:
            if dist == distance:
                if el == magnetic_atoms[0]:
                    dist_neighbNum[dist] += 1
                elif el == magnetic_atoms[1]:
                    dist_neighbNum[dist] -= 1
    return dist_neighbNum


def get_nn_list(path_to_poscar: str, magnetic_atom: str) -> list:
    nn_list = list(count_nn(path_to_poscar, magnetic_atoms=[
                   magnetic_atom, 'Po']).values())
    return nn_list



def get_spin(outcar_path : str) -> float:
    """
    Get total spin of first atom in FM structure to use as reference
    """

    try:
        outcar = Outcar(outcar_path)
        magnetization = outcar.magnetization
        return magnetization[0]['tot']
    except:
        return 0


def is_good_structure(struct_folder: str, ref_magmom: float) -> bool:
    """
    Check if structures after relaxation are sutable for
    futher Heisenberg hamiltonian calculations
    Return:
        True/False
    """
    vasprun_path = os.path.join(struct_folder, 'vasprun.xml')
    osz_path = os.path.join(struct_folder, 'OSZICAR')
    outcar_path = os.path.join(struct_folder, 'OUTCAR')

    assert os.path.exists(vasprun_path), 'File vasprun.xml absent! Cant continue :('
    assert os.path.exists(osz_path), 'File OSZICAR absent! Cant continue :('
    assert os.path.exists(outcar_path), 'File OUTCAR absent! Cant continue :('

    try:
        vasprun = Vasprun(vasprun_path, parse_dos=False, parse_eigen=False)
    except Exception:
        return False

    if not vasprun.converged * vasprun.converged_electronic * vasprun.converged_ionic:
        return False
    
    # drop structures with low spin
    if abs(get_spin(outcar_path)) < 0.9 * ref_magmom:
        return False
    
    return True


def find_good_structures(input_path: str, folder: str) -> list:
    good_struct_list = []
    bad_struct_list = []
    vasp_inputs_path = os.path.join(input_path, folder)
    assert os.path.exists(
        vasp_inputs_path), f'Path "{vasp_inputs_path}" Does not exist!'

    afm_outcar_path = os.path.join(vasp_inputs_path, 'fm0', 'OUTCAR')
    ref_magmom = get_spin(afm_outcar_path)

    
    for magnetic_conf in os.listdir(vasp_inputs_path):
        struct_folder = os.path.join(vasp_inputs_path, magnetic_conf)
        if is_good_structure(struct_folder, ref_magmom):
            good_struct_list.append(struct_folder)
        else:
            bad_struct_list.append(struct_folder)
    return good_struct_list, bad_struct_list


def energy_list_getter(good_struct_list: list, initial_atoms_num: int) -> list:
    E_list = []
    for struct_folder in tqdm(good_struct_list):
        vasprun_path = os.path.join(struct_folder, 'vasprun.xml')
        poscar_path = os.path.join(struct_folder, 'POSCAR')
        vasprun = Vasprun(vasprun_path, parse_dos=False, parse_eigen=False)
        ratio = get_ratio(poscar_path, initial_atoms_num)
        E_tot = vasprun.final_energy / ratio
        E_list.append(E_tot)
    return np.array(E_list)


def nn_matrix_getter(input_path: str, good_struct_list: list, magnetic_atom: str) -> list:
    good_structures_number = len(good_struct_list)
    nn_matrix = []
    for struct_folder in tqdm(good_struct_list):
        siman_path = os.path.join(input_path, 'siman_inputs',
                                  f'POSCAR_{struct_folder.split("/")[-1]}')
        nn_list = get_nn_list(path_to_poscar=siman_path,
                              magnetic_atom=magnetic_atom)
        nn_matrix.append(nn_list[:good_structures_number - 1])
    nn_matrix = np.append(np.ones([len(nn_matrix), 1]), nn_matrix, 1)
    return np.array(nn_matrix)


def sorted_matrix_getter(input_path: str, magnetic_atom: str, spin: float) -> list:
    good_struct_list, bad_struct_list = find_good_structures(
        input_path, folder='vasp_inputs')
    initial_atoms_num = len(Structure.from_file(
        os.path.join(input_path, 'POSCAR')))
    E_list = energy_list_getter(good_struct_list, initial_atoms_num)
    nn_matrix = nn_matrix_getter(input_path, good_struct_list, magnetic_atom)

    
    nn_spin_matrix = nn_matrix * spin * (spin + 1)
    
    full_matrix = np.append(
        nn_spin_matrix, E_list.reshape(len(E_list), 1), axis=1)
    
    sorted_matrix = full_matrix[np.argsort(full_matrix[:, -1])]
    
    return nn_matrix, sorted_matrix, good_struct_list, bad_struct_list


def exchange_coupling(matrix: list, energies: list) -> list:
    determinant = np.linalg.det(matrix)
    if determinant:
        solution_vector = np.linalg.solve(matrix, energies)
        return solution_vector


def j_vector_exact(sorted_matrix: list) -> list:
    """
    Exact solution of the system in case of nonzero determinant.
    If mapped coefficients form a singular matrix, the least stable structure
    excluded from the calculations until the determinant becomes nonzero.
    """
    energies = sorted_matrix[..., -1]
    matrix = sorted_matrix[..., :-1]

    matrix_size = matrix.shape[0]
    results = []
    for i in range(2, matrix_size + 1):
        tmp_matrix = matrix[:i, :i]
        tmp_energies = energies[:i]
        solution_vector = exchange_coupling(tmp_matrix, tmp_energies)
        if solution_vector is not None:
            results.append(solution_vector)

    E_geom_list = np.array([i[0] for i in results])
    j_vectors_list = [i[1:] for i in results]
    return E_geom_list, j_vectors_list


def j_vector_lstsq(sorted_matrix: list) -> list:
    """
    Estimate exchange coupling for the number of coordination spheres by the
    list squares method. Starting from the N by N system, step by step excluding
    one of the variables from the fitting, till the N by 2 system with only
    2 variables (Eg, J_1).
    """
    num_of_variables = sorted_matrix.shape[0]
    energies = sorted_matrix[..., -1]
    matrix = sorted_matrix[..., :-1]

    results = []
    for i in range(2, num_of_variables + 1):
        tmp_matrix = matrix[..., :i]
        x_lstsq = np.linalg.lstsq(tmp_matrix, energies)[0]
        results.append(x_lstsq)
    E_geom_list = np.array([i[0] for i in results])
    j_vectors_list = [i[1:] for i in results]
    return E_geom_list, j_vectors_list


def Tc_list_getter(j_vector_list: list, z_vector: list) -> list:
    T_c_list = []
    for j_vector in j_vector_list:
        z_vector_tmp = z_vector[:len(j_vector)]
        T_c = np.abs(2 * np.pi * sum(j_vector * z_vector_tmp) / (3 * k_B))
        T_c_list.append(T_c)
    T_c_list = np.array(T_c_list).round(1)
    return T_c_list


def write_output(input_path, j_exact_list, j_lstsq_list, z_vector, good_struct_list, bad_struct_list, nn_matrix, Egeom_exact_list, Egeom_lstsq_list, Tc_exact, Tc_lstsq):
    output_text = """
**********************************************************
*                   Curie Calculator                    *
**********************************************************
    """

    j_exact_str = 'Exchange coupling vector by exact solution (J, meV): \n \n'
    for i in j_exact_list:
        j_exact_str += '\t' + str(len(i)) + ' : ' + \
            str(np.round(i * 1000, 2)) + '\n'

    j_lstsq_str = 'Exchange coupling vector by least squares method (meV): \n \n'
    for i in j_lstsq_list:
        j_lstsq_str += '\t' + str(len(i)) + ' : ' + \
            str(np.round(i * 1000, 2)) + '\n' 

    j_joul_link = 'Exchange coupling vector by least squares method (Joule / link): \n \n'
    for j_vector in j_lstsq_list:
        j_link_vec = 1.60218e-19 * np.array(j_vector) / z_vector[:len(j_vector)]
        
        j_joul_link += '\t' + str(len(j_vector)) + ' : ' + \
            ' '.join([f'{i:.3e}' for i in j_link_vec]) + '\n' 
    
    good_structures_str = 'Good structures:\n\t' + \
        ' '.join([i.split('/')[-1] for i in sorted(good_struct_list)]) + '\n'
    bad_structures_str = 'bad structures: \n\t' + \
        ' '.join([i.split('/')[-1] for i in sorted(bad_struct_list)]) + '\n'

    output_text += good_structures_str
    output_text += '\n'
    output_text += bad_structures_str
    output_text += '\n'
    output_text += 'nn_matrix:\n' + str(nn_matrix) + '\n'

    output_text += '\n'
    output_text += '-' * 79 + '\n'
    output_text += 'Exact solution method: \n\n'
    output_text += 'E_geom, eV:\n\n\t' + str(Egeom_exact_list) + '\n\n'
    output_text += j_exact_str + '\n'
    output_text += '\n' + \
        'Critical temperature (Tc, K):' + '\n\n\t' + str(Tc_exact) + '\n'

    output_text += '\n'
    output_text += '-' * 79 + '\n'
    output_text += 'Least squares method: \n\n'
    output_text += 'E_geom, eV:\n\n\t' + str(Egeom_lstsq_list) + '\n\n'
    output_text += j_lstsq_str + '\n'
    output_text += j_joul_link + '\n'
    output_text += '\n' + \
        'Critical temperature (Tc, K):' + '\n\n\t' + str(Tc_lstsq) + '\n'

    output_path = os.path.join(input_path, 'output')
    if not os.path.exists(output_path):
        os.mkdir(output_path)

    out_file_path = os.path.join(output_path, 'OUTPUT.txt')

    print('\n', output_text, '\n')
    with open(out_file_path, 'w') as out_f:
        out_f.writelines(output_text)


def plot_j_values(input_path: str, j_vector_list: list, filename :str) -> None:
    plt.figure(figsize=(7, 5), dpi=200)
    j_vector_list_mev = [i * 1000 for i in j_vector_list]
    for y in j_vector_list_mev:
        x = range(1, len(y) + 1)
        plt.plot(x, y)
        plt.scatter(x, y, label=len(x))
    plt.xlabel('Coordination sphere number', fontsize=14)
    plt.ylabel('J, meV', fontsize=14)
    plt.xticks(range(1, len(j_vector_list[-1]) + 1))
    plt.grid(alpha=.4)
    plt.legend()

    output_path = os.path.join(input_path, 'output')
    if not os.path.exists(output_path):
        os.mkdir(output_path)

    out_file_path = os.path.join(output_path, filename)

    plt.savefig(out_file_path, bbox_inches='tight')


def plot_Tcs(input_path: str, Tc_lstsq: list, Tc_exact: list) -> None:
    """
Function plot the values of curie temperature versus coordination sphere number, i.e. shows how number of considered
nearest neighbours affect critical temperature
    Args:
        input_path: (str) path to your initial working folder
        Tc_lstsq: (list) Curie temperatures (K) calculated by least squares method for overdetermined system.
        Tc_exact: (list) Curie temperatures (K) calculated by exact solution of matrix.
    """
    plt.figure(figsize=(8, 6), dpi=200)
    plt.scatter(range(1, len(Tc_lstsq) + 1), Tc_lstsq,
                label='least squares', marker='v')
    plt.plot(range(1, len(Tc_lstsq) + 1), Tc_lstsq)
    plt.xlabel('Number of considered exchanges', fontsize=14)
    plt.ylabel(r'$T_C, K$', fontsize=14)
    plt.legend()
    plt.grid(alpha=.4)
    
    output_path = os.path.join(input_path, 'output')
    if not os.path.exists(output_path):
        os.mkdir(output_path)
    plt.savefig(os.path.join(output_path, 'Tcs_plot.png'), bbox_inches='tight')


def plot_E_tot(input_path: str, sorted_matrix: list, nn_matrix: list) -> None:

    E_tot_mev = np.array([i[-1] * 1000 for i in sorted_matrix])
    E_tot_norm = E_tot_mev - E_tot_mev.min()
    max_E_geom = max(E_tot_mev)
    min_E_geom = min(E_tot_mev)
    dE_geom = max_E_geom - min_E_geom
    text = f"""$dE$    :  {dE_geom:.2f}   meV
max : {max_E_geom:.2f}  meV
min  : {min_E_geom:.2f}   meV"""
    props = dict(boxstyle='round', facecolor='wheat', alpha=0.5)

    x = range(1, len(E_tot_norm) + 1)
    plt.figure(figsize=(7, 5), dpi=100)
    plt.scatter(x, E_tot_norm, color='r')
    plt.plot(x, E_tot_norm, color='r')
    plt.text(1, max(E_tot_norm), text, verticalalignment='top', bbox=props)
    plt.grid(alpha=.4)
    plt.xlabel('Spins (\u2191 - \u2193)', fontsize=12)
    plt.ylabel(r'$E_{tot},  meV$', fontsize=12)
    combination_list = [[int(p) for p in i[1:6]] for i in nn_matrix]
    plt.xticks(x, combination_list, rotation=10, ha='right')

    output_path = os.path.join(input_path, 'output')
    if not os.path.exists(output_path):
        os.mkdir(output_path)

    plt.savefig(os.path.join(output_path, 'E_tot_plot.png'),
                bbox_inches='tight')


def solver(input_path: str, magnetic_atom: str):
    spin_dict = {'Eu': 2.5, 'Fe': 2, 'Co': 1.5, 'Ni': 1, 'Cu': 0.5, 'Sm': 3, 'Nd': 1, 'Gd' : 0.5}

    
    # spin = get_spin(os.path.join(input_path, 'vasp_inputs', 'fm0', 'OUTCAR'))
    spin = spin_dict[magnetic_atom]

    nn_matrix, sorted_matrix, good_struct_list, bad_struct_list = sorted_matrix_getter(
        input_path, magnetic_atom, spin)
    
    Egeom_exact_list, j_exact_list = j_vector_exact(sorted_matrix)
    Egeom_lstsq_list, j_lstsq_list = j_vector_lstsq(sorted_matrix)

    z_vector = get_nn_list(path_to_poscar=os.path.join(input_path, 'POSCAR'),
                           magnetic_atom=magnetic_atom)

    Tc_exact = Tc_list_getter(j_exact_list, z_vector)
    Tc_lstsq = Tc_list_getter(j_lstsq_list, z_vector)

    write_output(input_path, j_exact_list, j_lstsq_list, z_vector,
                 good_struct_list, bad_struct_list,
                 nn_matrix, Egeom_exact_list,
                 Egeom_lstsq_list, Tc_exact, Tc_lstsq)
    print('OUTPUT.txt written')

    if len(j_exact_list):
        plot_j_values(input_path, j_exact_list, filename='J_exact')

    plot_j_values(input_path, j_lstsq_list, filename='J_least_sq')
    plot_Tcs(input_path, Tc_lstsq, Tc_exact)
    plot_E_tot(input_path, sorted_matrix, nn_matrix)
    print('All graphs are plotted')

    print('Calculations completed successfully!\n')


if __name__ == '__main__':
    input_path = os.getcwd()
    default_dict = update_defaults(input_path, DEFAULT_DICT)
    print(DEFAULT_DICT)
    solver(input_path, magnetic_atom =DEFAULT_DICT['MAGNETIC_ATOM'])
