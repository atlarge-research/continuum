"""\
Use the mathematical model from the paper, with data from the benchmark
"""

import argparse
from cgitb import enable
import logging
import subprocess
import pandas as pd
import datetime
import os
import matplotlib.pyplot as plt
import numpy as np
import time
import sys

sys.path.append(os.path.abspath('../'))

import main as cont_main

# Home dir should be continuum/
os.chdir('../')


def enable_logging(verbose):
    """Enable logging
    """
    # Set parameters
    level = logging.INFO
    if verbose:
        level = logging.DEBUG

    format = "[%(asctime)s %(filename)20s:%(lineno)4s - %(funcName)25s() ] %(message)s"
    logging.basicConfig(format=format, 
                        level=level, 
                        datefmt='%Y-%m-%d %H:%M:%S')

    logging.info('Logging has been enabled')


class Model():
    """Model template / super class
    """
    def __init__(self, args, config):
        self.resume = args.resume
        self.resume_index = 0

        # Set nodes/cores/quota/network
        self.E = config['infrastructure']['endpoint_nodes']

        if config['mode'] == 'cloud':
            self.C_w = config['infrastructure']['cloud_cores']
            self.Q_w = config['infrastructure']['cloud_quota']
            self.B = config['infrastructure']['cloud_endpoint_throughput']
        elif config['mode'] == 'edge':
            self.C_w = config['infrastructure']['edge_cores']
            self.Q_w = config['infrastructure']['edge_quota']
            self.B = config['infrastructure']['edge_endpoint_throughput']

        self.C_e = config['infrastructure']['endpoint_cores']
        self.Q_e = config['infrastructure']['endpoint_quota']

        # Set data frequency
        self.f = config['benchmark']['frequency']
        self.p = float(1 / self.f)

        # These variables will be used later on
        self.D = 0.0
        self.d = 0.0

        self.T_proc = 0.0
        self.T_pre = 0.0

        self.condition_proc = []
        self.condition_pre = []
        self.condition_net = []

    def execute(self, command):
        """Execute command

        Args:
            command (list(str)): Command to be executed
        """
        logging.info(' '.join(command))
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = [line.decode('utf-8') for line in process.stdout.readlines()]
        error = [line.decode('utf-8') for line in process.stderr.readlines()]
        return output, error

    def check_resume(self, local=True):
        """If the resume argument is given, get the first x log files >= the resume date,
        and use their output instead of re-running the experiment.
        """
        log_location = './logs'
        logs = [f for f in os.listdir(log_location) if f.endswith('.log')]
        logs.sort()
        index = 0

        for log in logs:
            # Filter on endpoint or cloud/edge
            if local and not 'endpoint' in log:
                continue
            if not local and not ('cloud' in log or 'edge' in log):
                continue

            splits = log.split('_')
            dt = splits[0] + '_' + splits[1]
            dt = datetime.datetime.strptime(dt, '%Y-%m-%d_%H:%M:%S')

            if dt >= self.resume:
                if index == self.resume_index:
                    path = log_location + '/' + log
                    logging.info('File %s for experiment run %i' % (path, index))

                    f = open(path, 'r')
                    output = [line for line in f.readlines()]
                    f.close()

                    self.resume_index += 1
                    return output, []
                else:
                    index += 1
        
        self.resume_index += 1
        return [], []

    def str_to_df(self, input):
        """Parse a csv as string to a Pandas DataFrame

        Args:
            input (str): Csv string to parse (e.g. a,b,c,d\ne,f,g,h\n)

        Returns:
            DataFrame: Pandas DataFrame containing the parsed Csv
        """
        # Split string into list
        l = [x.split(',') for x in input.split('\\n')]
        l = l[:-1]
        l = [sub[1:] for sub in l]

        # Split into header and data
        header = l[0]
        data = l[1:]

        # Convert into dataframe
        return pd.DataFrame(data, columns=header)


class ModelLocal(Model):
    """Model for local execution on endpoints
    """
    def __init__(self, args, parser):
        logging.info('Parse local config')
        config = cont_main.parse_config(parser, 'configuration/model/local.cfg')
        Model.__init__(self, args, config)

    def __repr__(self):
        return '''
--------------------------------------------------
Symbol      Explanation             Value
--------------------------------------------------
C_e         cores per endp.         %i
Q_e         endp. CPU core quota    %.2f
f           Frequency               %i Hz
p           Period (1/f)            %.2f
--------------------------------------------------
Acquired data
--------------------------------------------------
T_proc      norm. processing time   %.2f sec
--------------------------------------------------''' % (
            self.C_e, self.Q_e, self.f, self.p, self.T_proc)

    def benchmark_normalize(self):
        """Benchmark a local deployment (endpoint-only) for normalization
        """
        output = []
        if self.resume:
            output, _ = self.check_resume(local=True)

        if output == []:
            command = ['python3', 'main.py', '-v', 'configuration/model/local_normalize.cfg']
            output, _ = self.execute(command)

        # Parse output to dataframe
        df = self.str_to_df(output[-6][1:-2])
        logging.debug('\n' + df.to_string(index=False))

        # Extract the required data
        df['proc/data (ms)'] = pd.to_numeric(df['proc/data (ms)'], downcast='float')
        self.T_proc = df['proc/data (ms)'].mean() / 1000.0

    def condition_processing(self):
        """Model local, endpoint-only execution
        """
        result = self.T_proc / (self.C_e * self.Q_e)
        condition = self.p
        satisfy = result < condition

        logging.info('''
To satisfy: (T_proc / (C_e * Q_e)) < P
            (%.2f / (%i * %.2f)) < %.2f
            %.2f < %.2f
            %s''' % (
            self.T_proc, self.C_e, self.Q_e, self.p,
            result, condition,
            satisfy))

        self.condition_proc = [result, condition, satisfy]

    def satisfy(self):
        """Does local execution satisfy the conditions
        """
        satisfy = 'Not possible'
        if self.condition_proc[2]:
            satisfy = 'Possible'

        logging.info('Full processing on endpoints: %s' % (satisfy))

        if satisfy == 'Not possible':
            condition = []
            if not self.condition_proc[2]:
                condition.append('Insufficient compute capacity on endpoint')

            logging.info('Cause: %s' % (', '.join(condition)))

    def verify(self):
        """Benchmark a local deployment (endpoint-only) to verify the model
        """
        output = []
        if self.resume:
            output, _ = self.check_resume(local=True)

        if output == []:
            command = ['python3', 'main.py', '-v', 'configuration/model/local.cfg']
            output, _ = self.execute(command)

        # Parse output of endpoint to dataframe
        df = self.str_to_df(output[-6][1:-2])
        logging.info('\n' + df.to_string(index=False))


class ModelOffload(Model):
    """Model for local execution on endpoints
    """
    def __init__(self, args, parser):
        logging.info('Parse offload config')
        config = cont_main.parse_config(parser, 'configuration/model/offload.cfg')
        Model.__init__(self, args, config)

    def __repr__(self):
        return '''
--------------------------------------------------
Symbol      Explanation             Value
--------------------------------------------------
E           #endpoints              %i
C_w         cores per worker        %i
C_e         cores per endp.         %i
Q_w         worker CPU core quota   %.2f
Q_e         endp. CPU core quota    %.2f
B           bandwidth               %.2f Mbit
f           Frequency               %i Hz
p           Period (1/f)            %.2f
--------------------------------------------------
Acquired data
--------------------------------------------------
d           Size of 1 data entity   %.2f MB
D           Generated data / sec    %.2f Mbit
T_proc      norm. proc time         %.2f sec
T_pre       norm. preproc time      %.2f sec
--------------------------------------------------''' % (
            self.E, self.C_w, self.C_e, self.Q_w, self.Q_e,
            self.B, self.f, self.p,
            self.d, self.D, self.T_proc, self.T_pre)

    def benchmark_normalize(self):
        """Benchmark an edge offloading deployment for normalizaiton
        """
        output = []
        if self.resume:
            output, _ = self.check_resume(local=False)

        if output == []:
            command = ['python3', 'main.py', '-v', 'configuration/model/offload_normalize.cfg']
            output, _ = self.execute(command)

        # Parse output of worker to dataframe, and extract required data
        df_worker = self.str_to_df(output[-7][1:-2])
        logging.debug('\n' + df_worker.to_string(index=False))

        df_worker['proc/data (ms)'] = pd.to_numeric(df_worker['proc/data (ms)'], downcast='float')
        self.T_proc = df_worker['proc/data (ms)'].mean() / 1000.0

        # Parse output of endpoint to dataframe, and extract required data
        df_endpoint = self.str_to_df(output[-6][1:-2])
        logging.debug('\n' + df_endpoint.to_string(index=False))

        df_endpoint['preproc/data (ms)'] = pd.to_numeric(df_endpoint['preproc/data (ms)'], downcast='float')
        self.T_pre = df_endpoint['preproc/data (ms)'].mean() / 1000.0

        df_endpoint['data_size_avg (kb)'] = pd.to_numeric(df_endpoint['data_size_avg (kb)'], downcast='float')
        self.d = df_endpoint['data_size_avg (kb)'].mean() / 1000.0
        self.D = self.d * 8 * self.f

    def condition_processing(self):
        """Model worker data processing when offloading
        """
        result = (self.T_proc * self.E) / (self.C_w * self.Q_w)
        condition = self.p
        satisfy = result < condition

        logging.info('''
To satisfy: ((T_proc * E) / (C_w * Q_w)) < P
            ((%.2f * %i) / (%i * %.2f)) < %.2f 
            %.2f < %.2f
            %s''' % (
            self.T_proc, self.E, self.C_w, self.Q_w, self.p,
            result, condition,
            satisfy))

        self.condition_proc = [result, condition, satisfy]

    def condition_preprocessing(self):
        """Model endpoint preparation/preprocessing when offloading
        """
        result = self.T_pre / (self.C_e * self.Q_e)
        condition = self.p
        satisfy = result < condition

        logging.info('''
To satisfy: (T_pre / (C_e * Q_e)) < P
            (%.2f / (%i * %.2f)) < %.2f
            %.2f < %.2f
            %s''' % (
            self.T_pre, self.C_e, self.Q_e, self.p,
            result, condition,
            satisfy))

        self.condition_pre = [result, condition, satisfy]

    def condition_network(self):
        """Model bandwidth when offloading
        """
        result = self.D
        condition = self.B
        satisfy = result < condition

        logging.info('''
To satisfy: D < B
            %.2f < %.2f
            %s''' % (
            result, condition,
            satisfy))

        self.condition_net = [result, condition, satisfy]

    def satsify(self):
        """Does local execution satisfy the conditions
        """
        satisfy = 'Not possible'
        if self.condition_proc[2] and self.condition_pre[2] and self.condition_net[2]:
            satisfy = 'Possible'

        logging.info('Full offloading to workers: %s' % (satisfy))

        if satisfy == 'Not possible':
            condition = []
            if not self.condition_proc[2]:
                condition.append('Insufficient compute capacity on worker')
            if not self.condition_pre[2]:
                condition.append('Insufficient compute capacity on endpoints')
            if not self.condition_net[2]:
                condition.append('Insufficient network throughput')

            logging.info('Cause: %s' % (', '.join(condition)))

    def verify(self):
        """Benchmark an edge offloading deployment to verify the model
        """
        output = []
        if self.resume:
            output, _ = self.check_resume(local=False)

        if output == []:
            command = ['python3', 'main.py', '-v', 'configuration/model/offload.cfg']
            output, _ = self.execute(command)

        # Parse output of worker to dataframe
        df_worker = self.str_to_df(output[-7][1:-2])
        logging.info('\n' + df_worker.to_string(index=False))

        # Parse output of endpoint to dataframe
        df_endpoint = self.str_to_df(output[-6][1:-2])
        logging.info('\n' + df_endpoint.to_string(index=False))


def heatmap_truth(x, y, cutoff_endpoint, cutoff_edge, func):
    c1 = np.greater_equal(y, func(x))
    c2 = np.less_equal(y, func(cutoff_endpoint))
    c3 = np.less_equal(y, func(cutoff_edge))
    c4 = np.equal(y, y)

    return np.select([c1, c2, c3, c4], [-1.0, -0.33, 0.33, 1])


def heatmap(local, offload):
    # General plot info
    plt.rcParams.update({'font.size': 22})
    fig = plt.subplots(figsize =(12, 12))

    # Plot the no processing cut-off line
    cq_local = local.C_e * local.Q_e
    cq_offload = offload.C_w * offload.Q_w

    func = lambda a: local.p * a
    xlim = max(3, cq_local, cq_offload)
    ylim = func(xlim)

    # Plot cutoff between possible / not possible
    x = np.linspace(0, xlim, 1000)
    y = func(x)
    plt.plot(x, y, color='k', linestyle='-', linewidth=3)

    # Plot endpoint / edge / cloud cut-off lines
    cutoff_endpoint = 0.5
    cutoff_edge = 2.0

    plt.hlines(y=func(cutoff_endpoint), xmin=cutoff_endpoint, xmax=xlim, color='k', linestyle='-', linewidth=3)
    plt.hlines(y=func(cutoff_edge), xmin=cutoff_edge, xmax=xlim, color='k', linestyle='-', linewidth=3)

    # Plot the local / offload model result points
    plt.plot(cq_local, local.T_proc, 'ko', markersize=15)
    plt.text(cq_local+0.01, local.T_proc+0.01, 'Local')
    plt.plot(cq_offload, offload.T_proc * offload.E, 'ko', markersize=15)
    plt.text(cq_offload+0.01, offload.T_proc * offload.E + 0.01 , 'Offload')

    # Plot heatmap
    x2, y2 = np.meshgrid(np.linspace(0, xlim, 1000), np.linspace(0, ylim, 1000))
    z = heatmap_truth(x2, y2, cutoff_endpoint, cutoff_edge, func)
    z = z[:-1, :-1]
    z_min, z_max = -np.abs(z).max(), np.abs(z).max()
    from matplotlib import colors
    cmap = colors.ListedColormap(['#F8CECC', '#FFF2CC', '#DAE8FC', '#D5E8D4'])
    plt.pcolormesh(x2, y2, z, cmap=cmap, vmin=z_min, vmax=z_max)

    # Adding titles
    plt.xlabel('Compute Capacity')
    plt.ylabel('Compute Demand')

    # Set x/y range of plot
    plt.xlim(0.0, xlim)
    plt.ylim(0.0, ylim)

    # Save to file
    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    plt.savefig('./logs/heatmap2_%s.png' % (t), bbox_inches='tight')


def main(args, parser):
    """Main function

    Args:
        args (Namespace): Argparse object
        parser (ArgParse): Argparse object
    """
    logging.info('Local model')
    local = ModelLocal(args, parser)
    local.benchmark_normalize()
    logging.info(local)
    local.condition_processing()
    local.satisfy()
    local.verify()

    logging.info('Offload model')
    offload = ModelOffload(args, parser)
    offload.benchmark_normalize()
    logging.info(offload)
    offload.condition_processing()
    offload.condition_preprocessing()
    offload.condition_network()
    offload.satsify()
    offload.verify()

    # Plot heatmap graph
    heatmap(local, offload)


if __name__ == '__main__':
    """Get input arguments, and validate those arguments
    """
    parser = argparse.ArgumentParser()

    parser.add_argument('-v', '--verbose', action='store_true',
        help='increase verbosity level')
    parser.add_argument('-r', '--resume', type=lambda s: datetime.datetime.strptime(s, '%Y-%m-%d_%H:%M:%S'),
        help='Resume a previous figure replication from datetime "YYYY-MM-DD_HH:mm:ss"')
    args = parser.parse_args()

    enable_logging(args.verbose)
    main(args, parser)
